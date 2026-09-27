from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from friday.chat import ChatSession, MarkerFilter
from friday.config import load_config
from friday.core.events import (
    BrainError,
    BrainErrorKind,
    BrainEvent,
    Mode,
    RateLimitStatus,
    TextDelta,
    TurnCompleted,
)
from friday.core.ports import SessionState
from friday.core.prompt import MODE_CODE_ENABLED_NOTE

EXAMPLE = Path(__file__).parents[1] / "config" / "friday.example.yaml"
MODELS = load_config(EXAMPLE).models


class FakeBrain:
    def __init__(self, replies: list[list[BrainEvent]]) -> None:
        self._state = SessionState(Mode.CLAUDE, "opus", "Session 1")
        self.replies = replies
        self.sent: list[str] = []
        self.calls: list[str] = []
        self.last_rate_limit: RateLimitStatus | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    def send(self, text: str) -> None:
        self.sent.append(text)

    def events(self) -> Iterator[BrainEvent]:
        yield from self.replies.pop(0)

    def interrupt(self) -> None:
        self.calls.append("interrupt")

    def set_model(self, alias: str) -> None:
        self.calls.append(f"model:{alias}")
        self._state.model = alias

    def set_mode(self, mode: Mode) -> None:
        self.calls.append(f"mode:{mode}")
        self._state.mode = mode

    def new_session(self, name: str, mode: Mode, model: str) -> None:
        self._state = SessionState(mode, model, name)

    def resume_session(self, session_id: str, name: str, mode: Mode, model: str) -> None:
        self._state = SessionState(mode, model, name, session_id)

    def close(self) -> None:
        self.calls.append("close")


def reply(*chunks: str, error: BrainError | None = None) -> list[BrainEvent]:
    events: list[BrainEvent] = [TextDelta(chunk) for chunk in chunks]
    events.append(TurnCompleted("".join(chunks), "sid", error=error))
    return events


class Console:
    def __init__(self, answers: list[str] | None = None) -> None:
        self.output: list[str] = []
        self.answers = answers or []

    def write(self, text: str) -> None:
        self.output.append(text)

    def read(self, prompt: str) -> str:
        self.output.append(prompt)
        return self.answers.pop(0)

    @property
    def text(self) -> str:
        return "".join(self.output)


def session(brain: FakeBrain, console: Console) -> ChatSession:
    return ChatSession(brain, MODELS, write=console.write, read=console.read)


def test_marker_filter_hides_a_split_marker() -> None:
    marker = MarkerFilter("[MODE_CODE]")
    out = marker.feed("Il faut le mode code. [MODE") + marker.feed("_CODE]") + marker.flush()
    assert out == "Il faut le mode code. " and marker.seen


def test_marker_filter_releases_false_alarms() -> None:
    marker = MarkerFilter("[MODE_CODE]")
    out = marker.feed("Voir [MO") + marker.feed("NDE]") + marker.flush()
    assert out == "Voir [MONDE]" and not marker.seen


def test_streamed_answer_is_printed() -> None:
    brain, console = FakeBrain([reply("Bon", "jour.")]), Console()
    session(brain, console).handle("Salut")
    assert brain.sent == ["Salut"]
    assert "FRIDAY > Bonjour." in console.text


def test_model_command_switches_and_announces() -> None:
    brain, console = FakeBrain([]), Console()
    session(brain, console).handle("/model haïku")
    assert brain.calls == ["model:haiku"]
    assert "Je passe sur Haiku 4.5." in console.text


def test_unknown_model_keeps_the_current_one() -> None:
    brain, console = FakeBrain([]), Console()
    session(brain, console).handle("/model gpt")
    assert brain.calls == []
    assert "Je reste sur Opus 5.5" in console.text


def test_mode_command_switches_to_code_with_complex_model() -> None:
    brain, console = FakeBrain([]), Console()
    brain.state.model = "haiku"
    session(brain, console).handle("/mode code")
    assert brain.calls == ["mode:claude_code", "model:opus"]
    assert "Je passe en mode Claude Code. Je passe sur Opus 5.5." in console.text


def test_action_request_offers_code_mode_and_replays_it() -> None:
    brain = FakeBrain(
        [
            reply("Il faut passer en mode Claude Code. ", "[MODE_CODE]"),
            reply("C'est fait."),
        ]
    )
    console = Console(answers=["oui"])
    session(brain, console).handle("Crée un fichier notes.txt")
    assert "[MODE_CODE]" not in console.text
    assert "Tu veux que je passe en mode Claude Code ?" in console.text
    assert brain.state.mode is Mode.CLAUDE_CODE
    assert brain.sent[0] == "Crée un fichier notes.txt"
    assert brain.sent[1] == f"{MODE_CODE_ENABLED_NOTE}\nCrée un fichier notes.txt"


def test_declined_mode_switch_stays_in_conversation() -> None:
    brain = FakeBrain([reply("Il faut le mode Claude Code. [MODE_CODE]")])
    session(brain, Console(answers=["non"])).handle("Crée un fichier")
    assert brain.state.mode is Mode.CLAUDE and len(brain.sent) == 1


def test_quota_error_is_explained() -> None:
    error = BrainError(BrainErrorKind.RATE_LIMIT)
    brain, console = FakeBrain([reply(error=error)]), Console()
    session(brain, console).handle("Bonjour")
    assert "limite de mon abonnement" in console.text
    assert "Haiku 4.5" in console.text


def test_new_session_and_quit() -> None:
    brain, console = FakeBrain([]), Console()
    chat = session(brain, console)
    assert chat.handle("/session nouvelle Boucherie")
    assert brain.state.name == "Boucherie"
    assert chat.handle("/quitter") is False


def test_run_ignores_byte_order_mark_before_a_command() -> None:
    brain = FakeBrain([])
    console = Console(answers=["﻿/model haiku", "/quitter"])
    ChatSession(brain, MODELS, write=console.write, read=console.read).run()
    assert brain.calls == ["model:haiku", "close"]
    assert brain.sent == []


def test_run_closes_the_brain_on_eof() -> None:
    brain = FakeBrain([])

    def read(_: str) -> str:
        raise EOFError

    ChatSession(brain, MODELS, write=lambda _: None, read=read).run()
    assert brain.calls == ["close"]
