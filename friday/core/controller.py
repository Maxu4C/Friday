"""FRIDAY's application logic: what to do with each sentence of the user.

System commands (model, mode, sessions, state, control) are handled locally and
never reach Claude. Everything else goes to the brain, with the model picked by
the router unless the user locked one for the current session.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable, Generator, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from friday.core.events import (
    BrainEvent,
    Mode,
    PermissionRequest,
    RateLimitStatus,
    TextDelta,
    TurnCompleted,
)
from friday.core.intents import (
    AskMode,
    AskModel,
    AskUsage,
    AutoModel,
    Cancel,
    Command,
    CurrentSession,
    ForgetSession,
    IntentParser,
    ListSessions,
    MuteMic,
    NewSession,
    OpenClaudeWeb,
    RenameSession,
    Repeat,
    ResumeSession,
    SetMode,
    SetModel,
    Stop,
    Unclear,
    UnmuteMic,
)
from friday.core.messages import (
    MODE_LABELS,
    enumerate_fr,
    error_message,
    mode_switched,
    model_switched,
    relative_day,
)
from friday.core.ports import Brain, Storage
from friday.core.prompt import MODE_CODE_ENABLED_NOTE, MODE_CODE_MARKER
from friday.core.router import ModelRole, Router
from friday.core.safety import Risk, assess, is_final_confirmation
from friday.core.sessions import SessionNameTakenError, SessionRecord, SessionRegistry, summarize
from friday.core.text import MarkerFilter, is_no, is_yes, levenshtein, normalize
from friday.core.usage import UsageCounter

CLAUDE_WEB_URL = "https://claude.ai"
MAX_SPOKEN_SESSIONS = 5
_ORDINALS = {
    "premiere": 0, "la premiere": 0, "deuxieme": 1, "la deuxieme": 1, "seconde": 1,
    "la seconde": 1, "troisieme": 2, "la troisieme": 2,
}  # fmt: skip

# -- outputs -------------------------------------------------------------------------


@dataclass(frozen=True)
class Say:
    """A sentence FRIDAY produces locally (spoken, not sent to Claude)."""

    text: str


@dataclass(frozen=True)
class Ask:
    """A question: the next sentence of the user is its answer."""

    text: str


@dataclass(frozen=True)
class ShowSessions:
    sessions: tuple[SessionRecord, ...]
    current_key: str | None


@dataclass(frozen=True)
class StateChanged:
    session_name: str
    mode: Mode
    model: str
    model_label: str
    model_locked: bool
    mic_muted: bool = False


@dataclass(frozen=True)
class StopSpeaking:
    """The user asked for silence: cut the voice immediately."""


@dataclass(frozen=True)
class ConfirmAction:
    """Claude Code wants to run an action: ask the user, then call
    Controller.answer_confirmation() before reading the next output."""

    question: str  # spoken
    detail: str  # exact action, shown on screen
    dangerous: bool
    step: int  # 2 = second, explicit confirmation of a dangerous action


Output = Say | Ask | ShowSessions | StateChanged | StopSpeaking | ConfirmAction | BrainEvent


@dataclass(frozen=True)
class ControllerSettings:
    model_labels: Mapping[str, str]
    simple_model: str
    complex_model: str
    default_mode: Mode
    workspace: Path
    permission_timeout: float = 30.0


# -- pending questions ------------------------------------------------------------------


@dataclass(frozen=True)
class _ConfirmModeSwitch:
    request: str


@dataclass(frozen=True)
class _ConfirmCommand:
    command: Command


@dataclass(frozen=True)
class _ConfirmForget:
    record: SessionRecord


@dataclass(frozen=True)
class _ChooseSession:
    candidates: tuple[SessionRecord, ...]
    action: Literal["resume", "forget"]


_Pending = _ConfirmModeSwitch | _ConfirmCommand | _ConfirmForget | _ChooseSession
_Outputs = Generator[Output, None, None]


class Controller:
    def __init__(
        self,
        brain: Brain,
        parser: IntentParser,
        router: Router,
        settings: ControllerSettings,
        sessions_store: Storage,
        usage_store: Storage,
        *,
        now: Callable[[], datetime] = datetime.now,
        open_url: Callable[[str], object] = webbrowser.open,
    ) -> None:
        self._brain = brain
        self._parser = parser
        self._router = router
        self._settings = settings
        self._sessions_store = sessions_store
        self._usage_store = usage_store
        self._now = now
        self._open_url = open_url
        self._registry = SessionRegistry.from_dict(sessions_store.load())
        self._usage = UsageCounter.from_dict(usage_store.load())
        self._pending: _Pending | None = None
        self._confirmation: tuple[str, datetime] | None = None  # (answer, when)
        self._last_answer = ""
        self.mic_muted = False
        self._handlers: dict[type, Callable[[Any], _Outputs]] = {
            SetModel: self._set_model,
            AutoModel: self._auto_model,
            SetMode: self._set_mode,
            NewSession: self._new_session,
            ResumeSession: self._resume_session,
            ListSessions: self._list_sessions,
            RenameSession: self._rename_session,
            ForgetSession: self._forget_session,
            CurrentSession: self._current_session,
            AskModel: self._ask_model,
            AskMode: self._ask_mode,
            AskUsage: self._ask_usage,
            Stop: self._stop,
            Cancel: self._stop,
            Repeat: self._repeat,
            MuteMic: self._mute,
            UnmuteMic: self._unmute,
            OpenClaudeWeb: self._open_web,
        }

    # -- public API ------------------------------------------------------------------

    @property
    def current(self) -> SessionRecord:
        record = self._registry.current
        assert record is not None, "call start() first"
        return record

    @property
    def sessions(self) -> list[SessionRecord]:
        return self._registry.records

    @property
    def awaiting_answer(self) -> bool:
        return self._pending is not None

    @property
    def model_choices(self) -> list[tuple[str, str]]:
        """(alias, label) of the models the interface may offer."""
        return list(self._settings.model_labels.items())

    @property
    def active_model(self) -> str:
        return self._brain.state.model

    def usage_today(self) -> dict[str, int]:
        """Requests sent to Claude today, per model label."""
        counts = self._usage.day(self._now().date())
        return {self._label(model): n for model, n in counts.most_common()}

    @property
    def rate_limit(self) -> RateLimitStatus | None:
        return self._brain.last_rate_limit

    def start(self) -> Iterator[Output]:
        """Reopen the last active session (or create the first one) and announce it."""
        record = self._registry.current or next(iter(self._registry.records), None)
        if record is None:
            record = self._create(None)
            yield Say(f"Bonjour. Nouvelle session : {record.name}, {self._describe(record)}.")
        else:
            self._registry.activate(record, self._now())
            self._load(record)
            self._save()
            yield Say(f"Session {record.name}, {self._describe(record)}.")
        yield self._state()

    def handle(self, text: str) -> Iterator[Output]:
        text = text.strip()
        if not text:
            return
        pending, self._pending = self._pending, None
        if pending is not None:
            handled = yield from self._answer(pending, text)
            if handled:
                return
        intent = self._parser.parse(text)
        if isinstance(intent, Unclear):
            self._pending = _ConfirmCommand(intent.guess)
            yield Ask(self._clarify(intent.guess))
        elif intent is not None:
            yield from self.execute(intent)
        else:
            yield from self._ask_claude(text)

    def execute(self, command: Command) -> Iterator[Output]:
        """Run a system command (also used by the text and graphical interfaces)."""
        yield from self._handlers[type(command)](command)

    def interrupt(self) -> None:
        """Stop the running request (callable from another thread)."""
        self._brain.interrupt()

    @property
    def permission_timeout(self) -> float:
        return self._settings.permission_timeout

    def answer_confirmation(self, answer: str) -> None:
        """The user's reply to the last ConfirmAction ("oui", "non", "oui, confirme"...)."""
        self._confirmation = (answer, self._now())

    def close(self) -> None:
        self._brain.close()
        self._save()

    # -- Claude ------------------------------------------------------------------------

    def _ask_claude(self, text: str) -> _Outputs:
        record = self.current
        model = self._pick_model(record, text)
        if self._brain.state.model != model:
            self._brain.set_model(model)
        self._usage.record(model, self._now())
        self._usage_store.save(self._usage.to_dict())

        marker = MarkerFilter(MODE_CODE_MARKER)
        answer: list[str] = []
        completed = False
        self._brain.send(text)
        try:
            for event in self._brain.events():
                if isinstance(event, TextDelta):
                    chunk = marker.feed(event.text)
                    if chunk:
                        answer.append(chunk)
                        yield TextDelta(chunk)
                    continue
                if isinstance(event, PermissionRequest):
                    yield from self._ask_permission(event)
                    continue
                if isinstance(event, TurnCompleted):
                    completed = True
                    tail = marker.flush()
                    if tail:
                        answer.append(tail)
                        yield TextDelta(tail)
                    yield event
                    yield from self._after_turn(record, text, event, "".join(answer), marker.seen)
                    return
                yield event
        finally:
            if not completed:
                # The consumer stopped listening (e.g. closed generator): finish the turn.
                self._brain.interrupt()
                for _ in self._brain.events():
                    pass

    def _after_turn(
        self,
        record: SessionRecord,
        request: str,
        event: TurnCompleted,
        answer: str,
        wants_code: bool,
    ) -> _Outputs:
        record.session_id = self._brain.state.session_id
        record.model = self._brain.state.model
        record.last_used_at = self._now()
        if event.error is not None:
            self._save()
            message = error_message(
                event.error,
                self._label(self._brain.state.model),
                self._label(self._settings.simple_model),
            )
            self._last_answer = message
            yield Say(message)
            return
        record.summary = summarize(answer) or record.summary
        self._last_answer = answer.strip()
        self._save()
        if wants_code and record.mode is Mode.CLAUDE:
            self._pending = _ConfirmModeSwitch(request)
            yield Ask("Voulez-vous que je passe en mode Claude Code ?")

    # -- permissions ------------------------------------------------------------------------

    def _ask_permission(self, request: PermissionRequest) -> _Outputs:
        assessment = assess(request.tool, request.input, request.description)
        dangerous = assessment.risk is Risk.DANGEROUS
        question = f"{assessment.spoken}."
        if dangerous:
            question += f" Attention, action à risque : {assessment.reason}."
        question += " Vous confirmez ?"
        answer = yield from self._confirm(ConfirmAction(question, assessment.detail, dangerous, 1))
        allowed, message = False, "Refusé par l'utilisateur."
        if answer is None:
            message = "Pas de réponse de l'utilisateur à temps."
            yield Say("Sans réponse de votre part, j'ai refusé.")
        elif is_yes(answer) or (dangerous and is_final_confirmation(answer)):
            if not dangerous:
                allowed = True
            else:
                final = yield from self._confirm(
                    ConfirmAction(
                        "C'est irréversible. Pour exécuter, dites : oui, confirme.",
                        assessment.detail,
                        True,
                        2,
                    )
                )
                allowed = final is not None and is_final_confirmation(final)
                if not allowed:
                    message = "Pas de confirmation explicite."
                    yield Say("Sans confirmation explicite, j'ai refusé.")
        elif is_no(answer) or isinstance(self._parser.parse(answer), Stop | Cancel):
            yield Say("D'accord, je refuse.")
        else:
            message = "Réponse incomprise."
            yield Say("Je n'ai pas compris, je refuse par sécurité.")
        self._brain.respond_permission(request, allowed, "" if allowed else message)
        if allowed:
            yield Say("Entendu.")

    def _confirm(self, action: ConfirmAction) -> Generator[Output, None, str | None]:
        """Ask and return the answer, or None if there was none in time."""
        self._confirmation = None
        asked_at = self._now()
        yield action
        answer, self._confirmation = self._confirmation, None
        if answer is None:
            return None
        text, answered_at = answer
        if not text.strip():
            return None
        if (answered_at - asked_at).total_seconds() > self._settings.permission_timeout:
            return None
        return text

    def _pick_model(self, record: SessionRecord, text: str) -> str:
        if record.model_lock:
            return record.model_lock
        route = self._router.route(text, record.mode)
        if route.role is ModelRole.SIMPLE:
            return self._settings.simple_model
        return self._settings.complex_model

    # -- answers to questions --------------------------------------------------------------

    def _answer(self, pending: _Pending, text: str) -> Generator[Output, None, bool]:
        if isinstance(pending, _ChooseSession):
            chosen = self._choose(pending.candidates, text)
            if chosen is None:
                if is_no(text):
                    yield Say("D'accord.")
                    return True
                return False
            if pending.action == "resume":
                yield from self._switch_to(chosen)
            else:
                yield from self._confirm_forget(chosen)
            return True
        if not (is_yes(text) or is_no(text)):
            return False  # not an answer: treat it as a new request
        yes = is_yes(text)
        if isinstance(pending, _ConfirmModeSwitch):
            if yes:
                yield from self._switch_mode(Mode.CLAUDE_CODE)
                yield from self._ask_claude(f"{MODE_CODE_ENABLED_NOTE}\n{pending.request}")
            else:
                yield Say("D'accord, je reste en mode Claude.")
        elif isinstance(pending, _ConfirmCommand):
            if yes:
                yield from self.execute(pending.command)
            else:
                yield Say("D'accord.")
        elif yes:
            yield from self._forget(pending.record)
        else:
            yield Say(f"D'accord, je garde la session {pending.record.name}.")
        return True

    @staticmethod
    def _choose(candidates: tuple[SessionRecord, ...], text: str) -> SessionRecord | None:
        spoken = normalize(text)
        if spoken in _ORDINALS and _ORDINALS[spoken] < len(candidates):
            return candidates[_ORDINALS[spoken]]
        best = min(candidates, key=lambda r: levenshtein(spoken, normalize(r.name)))
        name = normalize(best.name)
        if levenshtein(spoken, name) <= 2 or (len(spoken) >= 3 and spoken in name):
            return best
        return None

    # -- model and mode --------------------------------------------------------------------

    def _set_model(self, command: SetModel) -> _Outputs:
        record = self.current
        record.model_lock = command.alias
        if self._brain.state.model != command.alias:
            self._brain.set_model(command.alias)
        record.model = self._brain.state.model
        self._save()
        yield Say(model_switched(self._label(command.alias)))
        yield self._state()
        if command.rest:
            yield from self._ask_claude(command.rest)

    def _auto_model(self, _: AutoModel) -> _Outputs:
        self.current.model_lock = None
        self._save()
        simple = self._label(self._settings.simple_model)
        complex_ = self._label(self._settings.complex_model)
        yield Say(
            f"Je choisis de nouveau le modèle automatiquement : {simple} pour les questions "
            f"simples, {complex_} pour le reste."
        )
        yield self._state()

    def _set_mode(self, command: SetMode) -> _Outputs:
        if command.mode is self.current.mode:
            yield Say(f"Nous sommes déjà en mode {MODE_LABELS[command.mode]}.")
        else:
            yield from self._switch_mode(command.mode)
        if command.rest:
            yield from self._ask_claude(command.rest)

    def _switch_mode(self, mode: Mode) -> _Outputs:
        record = self.current
        self._brain.set_mode(mode)
        record.mode = mode
        message = mode_switched(mode)
        if mode is Mode.CLAUDE_CODE and not record.model_lock:
            complex_ = self._settings.complex_model
            if self._brain.state.model != complex_:
                self._brain.set_model(complex_)
                message += " " + model_switched(self._label(complex_))
        record.model = self._brain.state.model
        self._save()
        yield Say(message)
        yield self._state()

    # -- sessions ---------------------------------------------------------------------------

    def _new_session(self, command: NewSession) -> _Outputs:
        try:
            record = self._create(command.name)
        except SessionNameTakenError:
            self._pending = _ConfirmCommand(ResumeSession(command.name))
            yield Ask(f"Une session s'appelle déjà {command.name}. Voulez-vous la reprendre ?")
            return
        yield Say(f"Nouvelle session : {record.name}, {self._describe(record)}.")
        yield self._state()

    def _resume_session(self, command: ResumeSession) -> _Outputs:
        if command.name is None:
            previous = self._registry.previous()
            if previous is None:
                yield Say("Il n'y a pas d'autre session.")
            else:
                yield from self._switch_to(previous)
            return
        matches = self._registry.find(command.name)
        if not matches:
            yield Say(f"Je ne trouve pas de session {command.name}.")
        elif len(matches) == 1:
            yield from self._switch_to(matches[0])
        else:
            self._pending = _ChooseSession(tuple(matches), "resume")
            yield Ask(f"J'ai trouvé {enumerate_fr([r.name for r in matches])}. Laquelle ?")

    def _switch_to(self, record: SessionRecord) -> _Outputs:
        if record is self._registry.current:
            yield Say(f"Nous sommes déjà sur la session {record.name}.")
            return
        self._registry.activate(record, self._now())
        self._load(record)
        self._save()
        yield Say(f"Je reprends la session {record.name}, {self._describe(record)}.")
        yield self._state()

    def _list_sessions(self, _: ListSessions) -> _Outputs:
        records = self._registry.records
        current = self._registry.current
        yield ShowSessions(tuple(records), current.key if current else None)
        today = self._now().date()
        spoken = []
        for record in records[:MAX_SPOKEN_SESSIONS]:
            item = (
                f"{record.name}, mode {MODE_LABELS[record.mode]}, "
                f"{relative_day(record.last_used_at.date(), today)}"
            )
            if record.summary:
                item += f" : {record.summary.rstrip('.')}"
            spoken.append(item)
        count = len(records)
        text = f"Vous avez {count} session{'s' if count > 1 else ''} : {enumerate_fr(spoken)}."
        if count > MAX_SPOKEN_SESSIONS:
            text += f" Et {count - MAX_SPOKEN_SESSIONS} autres, affichées à l'écran."
        yield Say(text)

    def _rename_session(self, command: RenameSession) -> _Outputs:
        record = self.current
        try:
            self._registry.rename(record, command.name)
        except SessionNameTakenError as exc:
            yield Say(str(exc))
            return
        self._brain.state.name = record.name
        self._save()
        yield Say(f"Cette session s'appelle maintenant {record.name}.")
        yield self._state()

    def _forget_session(self, command: ForgetSession) -> _Outputs:
        if command.name is None:
            yield from self._confirm_forget(self.current)
            return
        matches = self._registry.find(command.name)
        if not matches:
            yield Say(f"Je ne trouve pas de session {command.name}.")
        elif len(matches) == 1:
            yield from self._confirm_forget(matches[0])
        else:
            self._pending = _ChooseSession(tuple(matches), "forget")
            yield Ask(f"J'ai trouvé {enumerate_fr([r.name for r in matches])}. Laquelle ?")

    def _confirm_forget(self, record: SessionRecord) -> _Outputs:
        self._pending = _ConfirmForget(record)
        yield Ask(f"Voulez-vous vraiment que j'oublie la session {record.name} ?")

    def _forget(self, record: SessionRecord) -> _Outputs:
        was_current = record is self._registry.current
        self._registry.forget(record)
        message = (
            f"J'ai oublié la session {record.name}. "
            "Sa conversation reste enregistrée dans Claude Code."
        )
        if was_current:
            following = self._registry.previous()
            if following is None:
                following = self._create(None)
            else:
                self._registry.activate(following, self._now())
                self._load(following)
            message += f" Nous passons sur la session {following.name}."
        self._save()
        yield Say(message)
        yield self._state()

    def _current_session(self, _: CurrentSession) -> _Outputs:
        record = self.current
        yield Say(f"Nous sommes sur la session {record.name}, {self._describe(record)}.")

    # -- state and control ---------------------------------------------------------------------

    def _ask_model(self, _: AskModel) -> _Outputs:
        record = self.current
        label = self._label(self._brain.state.model)
        if record.model_lock:
            yield Say(f"J'utilise {label}, comme vous l'avez demandé.")
            return
        simple = self._label(self._settings.simple_model)
        complex_ = self._label(self._settings.complex_model)
        yield Say(
            f"Je choisis automatiquement : {simple} pour les questions simples, {complex_} "
            f"pour le reste. En ce moment, {label}."
        )

    def _ask_mode(self, _: AskMode) -> _Outputs:
        yield Say(f"Nous sommes en mode {MODE_LABELS[self.current.mode]}.")

    def _ask_usage(self, _: AskUsage) -> _Outputs:
        counts = self._usage.day(self._now().date())
        total = sum(counts.values())
        if total == 0:
            text = "Aucune requête à Claude aujourd'hui."
        elif len(counts) == 1:
            model = next(iter(counts))
            plural = "s" if total > 1 else ""
            text = f"Aujourd'hui, {total} requête{plural} à Claude, sur {self._label(model)}."
        else:
            details = [f"{n} sur {self._label(model)}" for model, n in counts.most_common()]
            text = f"Aujourd'hui, {total} requêtes à Claude : {enumerate_fr(details)}."
        limit = self._brain.last_rate_limit
        if limit is not None and "five_hour" in limit.utilization:
            used = round(limit.utilization["five_hour"] * 100)
            text += f" Quota sur cinq heures utilisé à {used} %."
        yield Say(text)

    def _stop(self, _: Command) -> _Outputs:
        self._brain.interrupt()
        yield StopSpeaking()
        yield Say("D'accord.")

    def _repeat(self, _: Repeat) -> _Outputs:
        yield Say(self._last_answer or "Je n'ai encore rien dit.")

    def _mute(self, _: MuteMic) -> _Outputs:
        self.mic_muted = True
        yield Say("Micro coupé. Utilisez le raccourci clavier pour me parler.")
        yield self._state()

    def _unmute(self, _: UnmuteMic) -> _Outputs:
        self.mic_muted = False
        yield Say("Micro réactivé.")
        yield self._state()

    def _open_web(self, _: OpenClaudeWeb) -> _Outputs:
        self._open_url(CLAUDE_WEB_URL)
        yield Say("J'ouvre Claude dans votre navigateur.")

    # -- helpers ----------------------------------------------------------------------------

    def _create(self, name: str | None) -> SessionRecord:
        record = self._registry.create(
            name,
            self._settings.default_mode,
            self._settings.complex_model,
            str(self._settings.workspace),
            self._now(),
        )
        self._load(record)
        self._save()
        return record

    def _load(self, record: SessionRecord) -> None:
        workspace = Path(record.workspace) if record.workspace else None
        if record.session_id:
            self._brain.resume_session(
                record.session_id, record.name, record.mode, record.model, workspace
            )
        else:
            self._brain.new_session(record.name, record.mode, record.model, workspace)

    def _save(self) -> None:
        self._sessions_store.save(self._registry.to_dict())

    def _label(self, model: str) -> str:
        return self._settings.model_labels.get(model, model)

    def _describe(self, record: SessionRecord) -> str:
        model = self._label(record.model_lock) if record.model_lock else "modèle automatique"
        return f"mode {MODE_LABELS[record.mode]}, {model}"

    def _clarify(self, guess: Command) -> str:
        if isinstance(guess, SetModel):
            return f"Voulez-vous passer sur {self._label(guess.alias)} ?"
        if isinstance(guess, SetMode):
            return f"Voulez-vous passer en mode {MODE_LABELS[guess.mode]} ?"
        if isinstance(guess, ResumeSession):
            return f"Voulez-vous reprendre la session {guess.name} ?"
        return "Voulez-vous que je fasse cela ?"

    def _state(self) -> StateChanged:
        record = self.current
        return StateChanged(
            session_name=record.name,
            mode=record.mode,
            model=self._brain.state.model,
            model_label=self._label(self._brain.state.model),
            model_locked=record.model_lock is not None,
            mic_muted=self.mic_muted,
        )
