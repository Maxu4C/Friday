"""`friday chat`: text conversation with FRIDAY (before the audio pipeline exists)."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

from friday.config import ModelsConfig
from friday.core.events import Mode, TextDelta, ToolResult, ToolUse, TurnCompleted
from friday.core.messages import MODE_LABELS, error_message, mode_switched, model_switched
from friday.core.ports import Brain
from friday.core.prompt import MODE_CODE_ENABLED_NOTE, MODE_CODE_MARKER

HELP = """Commandes :
  /mode                  affiche le mode ; /mode claude | /mode code pour changer
  /model                 affiche les modèles ; /model <nom> pour changer (ex. /model haiku)
  /session               affiche la session ; /session nouvelle [nom] ; /session <id> [nom]
  /etat                  mode, modèle, session et quota
  /aide                  cette aide
  /quitter               quitter
Ctrl+C pendant une réponse l'interrompt."""

_YES = {"oui", "o", "ouais", "yes", "y", "vas-y", "ok", "d'accord"}
_MODE_WORDS = {
    "claude": Mode.CLAUDE,
    "conversation": Mode.CLAUDE,
    "code": Mode.CLAUDE_CODE,
    "claude code": Mode.CLAUDE_CODE,
    "claude_code": Mode.CLAUDE_CODE,
    "action": Mode.CLAUDE_CODE,
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join(
        "".join(c for c in decomposed if not unicodedata.combining(c)).casefold().split()
    )


class MarkerFilter:
    """Hide a marker from streamed text, even when split across several chunks."""

    def __init__(self, marker: str) -> None:
        self._marker = marker
        self._held = ""
        self.seen = False

    def feed(self, text: str) -> str:
        data = self._held + text
        if self._marker in data:
            data = data.replace(self._marker, "")
            self.seen = True
        keep = 0
        for size in range(min(len(self._marker) - 1, len(data)), 0, -1):
            if self._marker.startswith(data[-size:]):
                keep = size
                break
        self._held = data[len(data) - keep :] if keep else ""
        return data[: len(data) - keep]

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held


class ChatSession:
    def __init__(
        self,
        brain: Brain,
        models: ModelsConfig,
        *,
        write: Callable[[str], None],
        read: Callable[[str], str],
    ) -> None:
        self._brain = brain
        self._models = models
        self._write = write
        self._read = read
        self._session_count = 1

    def run(self) -> int:
        state = self._brain.state
        self._say(
            f"Bonjour. Mode {MODE_LABELS[state.mode]}, {self._models.label(state.model)}. "
            "Tape /aide pour les commandes."
        )
        try:
            while True:
                try:
                    # PowerShell may prefix piped input with a UTF-8 byte order mark.
                    line = self._read("\nToi > ").lstrip("﻿").strip()
                except EOFError:
                    break
                if line and not self.handle(line):
                    break
        except KeyboardInterrupt:
            self._write("\n")
        finally:
            self._brain.close()
        self._say("À plus tard.")
        return 0

    def handle(self, line: str) -> bool:
        """Process one input line; return False to quit."""
        if not line.startswith("/"):
            self.ask(line)
            return True
        command, _, argument = line[1:].partition(" ")
        command, argument = _normalize(command), argument.strip()
        if command in {"quitter", "quit", "exit", "q"}:
            return False
        handlers: dict[str, Callable[[str], None]] = {
            "aide": self._help,
            "help": self._help,
            "mode": self._mode,
            "model": self._model,
            "modele": self._model,
            "session": self._session,
            "etat": self._status,
        }
        handler = handlers.get(command)
        if handler is None:
            self._say(f"Commande inconnue : /{command}. Tape /aide.")
        else:
            handler(argument)
        return True

    def ask(self, text: str) -> None:
        marker = MarkerFilter(MODE_CODE_MARKER)
        result = self._stream(text, marker)
        if result is None:
            return
        if result.error is not None:
            self._say(self._error_text(result))
            return
        if marker.seen and self._brain.state.mode is Mode.CLAUDE:
            answer = self._read("\nFRIDAY > Tu veux que je passe en mode Claude Code ? (oui/non) ")
            if _normalize(answer) in _YES:
                self._switch_mode(Mode.CLAUDE_CODE)
                self.ask(f"{MODE_CODE_ENABLED_NOTE}\n{text}")

    # -- commands -------------------------------------------------------------

    def _help(self, _: str) -> None:
        self._write(HELP + "\n")

    def _mode(self, argument: str) -> None:
        if not argument:
            self._say(f"On est en mode {MODE_LABELS[self._brain.state.mode]}.")
            return
        mode = _MODE_WORDS.get(_normalize(argument))
        if mode is None:
            self._say("Je connais les modes claude et code.")
        elif mode is self._brain.state.mode:
            self._say(f"On est déjà en mode {MODE_LABELS[mode]}.")
        else:
            self._switch_mode(mode)

    def _model(self, argument: str) -> None:
        current = self._brain.state.model
        if not argument:
            names = ", ".join(
                f"{info.alias} ({info.label})" for info in self._models.available.values()
            )
            self._say(f"J'utilise {self._models.label(current)}. Disponibles : {names}.")
            return
        alias = self._find_model(argument)
        if alias is None:
            label = self._models.label(current)
            self._say(f"Je ne connais pas le modèle {argument}. Je reste sur {label}.")
        elif alias == current:
            self._say(f"J'utilise déjà {self._models.label(alias)}.")
        else:
            self._brain.set_model(alias)
            self._say(model_switched(self._models.label(self._brain.state.model)))

    def _session(self, argument: str) -> None:
        state = self._brain.state
        if not argument:
            self._say(
                f"{state.name}, mode {MODE_LABELS[state.mode]}, {self._models.label(state.model)}, "
                f"identifiant {state.session_id or 'pas encore attribué'}."
            )
            return
        first, _, rest = argument.partition(" ")
        if _normalize(first) in {"nouvelle", "new"}:
            self._session_count += 1
            name = rest.strip() or f"Session {self._session_count}"
            self._brain.new_session(name, state.mode, state.model)
            self._say(f"Nouvelle session : {name}.")
        else:
            name = rest.strip() or f"Session {first[:8]}"
            self._brain.resume_session(first, name, state.mode, state.model)
            self._say(f"Je reprends la session {name}.")

    def _status(self, _: str) -> None:
        state = self._brain.state
        text = f"Mode {MODE_LABELS[state.mode]}, {self._models.label(state.model)}, {state.name}."
        limit = self._brain.last_rate_limit
        if limit is not None and limit.utilization:
            used = ", ".join(f"{k} {round(v * 100)} %" for k, v in limit.utilization.items())
            text += f" Quota utilisé : {used}."
        self._say(text)

    # -- helpers ----------------------------------------------------------------

    def _stream(self, text: str, marker: MarkerFilter) -> TurnCompleted | None:
        self._brain.send(text)
        started = False
        while True:
            try:
                for event in self._brain.events():
                    if isinstance(event, TextDelta):
                        chunk = marker.feed(event.text)
                        if chunk and not started:
                            self._write("\nFRIDAY > ")
                            started = True
                        self._write(chunk)
                    elif isinstance(event, ToolUse):
                        self._write(f"\n  [outil] {event.name} {_brief(event.input)}")
                        started = False
                    elif isinstance(event, ToolResult) and event.is_error:
                        self._write(f"\n  [échec] {event.summary}")
                    elif isinstance(event, TurnCompleted):
                        self._write(marker.flush())
                        if event.permission_denials:
                            denied = ", ".join(event.permission_denials)
                            self._write(f"\n  [refusé] {denied}")
                        if started:
                            self._write("\n")
                        return event
                return None
            except KeyboardInterrupt:
                self._brain.interrupt()

    def _switch_mode(self, mode: Mode) -> None:
        self._brain.set_mode(mode)
        message = mode_switched(mode)
        if mode is Mode.CLAUDE_CODE and self._brain.state.model != self._models.complex:
            self._brain.set_model(self._models.complex)
            message += " " + model_switched(self._models.label(self._models.complex))
        self._say(message)

    def _find_model(self, spoken: str) -> str | None:
        wanted = _normalize(spoken)
        for info in self._models.available.values():
            if wanted in {_normalize(info.alias), _normalize(info.label)} | {
                _normalize(s) for s in info.spoken
            }:
                return info.alias
        return None

    def _error_text(self, result: TurnCompleted) -> str:
        assert result.error is not None
        state = self._brain.state
        return error_message(
            result.error,
            self._models.label(state.model),
            self._models.label(self._models.simple),
        )

    def _say(self, text: str) -> None:
        self._write(f"\nFRIDAY > {text}\n")


def _brief(data: dict[str, object], limit: int = 80) -> str:
    for key in ("command", "file_path", "pattern", "path", "url"):
        if key in data:
            text = str(data[key])
            return text if len(text) <= limit else text[: limit - 1] + "…"
    return ""
