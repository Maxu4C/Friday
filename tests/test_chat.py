"""`friday chat` renders the Controller and maps slash shortcuts to commands."""

from __future__ import annotations

from friday.chat import ChatSession
from friday.core.events import Mode
from friday.core.text import MarkerFilter
from tests.fakes import answer
from tests.test_controller import Harness


class Console:
    def __init__(self, answers: list[str] | None = None) -> None:
        self.output: list[str] = []
        self.answers = answers or []

    def write(self, text: str) -> None:
        self.output.append(text)

    def read(self, prompt: str) -> str:
        self.output.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)

    @property
    def text(self) -> str:
        return "".join(self.output)


def chat(harness: Harness, console: Console) -> ChatSession:
    return ChatSession(harness.controller, write=console.write, read=console.read)


def test_marker_filter_hides_a_split_marker() -> None:
    marker = MarkerFilter("[MODE_CODE]")
    out = marker.feed("Il faut le mode code. [MODE") + marker.feed("_CODE]") + marker.flush()
    assert out == "Il faut le mode code. " and marker.seen


def test_marker_filter_releases_false_alarms() -> None:
    marker = MarkerFilter("[MODE_CODE]")
    out = marker.feed("Voir [MO") + marker.feed("NDE]") + marker.flush()
    assert out == "Voir [MONDE]" and not marker.seen


def test_streamed_answer_is_printed() -> None:
    harness, console = Harness([answer("Bon", "jour.")]), Console()
    chat(harness, console).handle("Salut")
    assert "FRIDAY > Bonjour." in console.text


def test_plain_sentences_are_commands_too() -> None:
    harness, console = Harness(), Console()
    chat(harness, console).handle("utilise Haiku")
    assert "FRIDAY > Je passe sur Haiku 4.5." in console.text
    assert harness.brain.sent == []


def test_slash_shortcuts() -> None:
    harness, console = Harness(), Console()
    session = chat(harness, console)
    session.handle("/model fable")
    session.handle("/mode code")
    session.handle("/session nouvelle Boucherie")
    session.handle("/sessions")
    session.handle("/model auto")
    assert harness.controller.current.name == "Boucherie"
    assert harness.controller.current.mode is Mode.CLAUDE
    assert "Je passe sur Fable 5.1." in console.text
    assert "Je passe en mode Claude Code." in console.text
    assert "* Boucherie · Claude · auto" in console.text
    assert harness.brain.sent == []


def test_unknown_shortcut() -> None:
    harness, console = Harness(), Console()
    chat(harness, console).handle("/bidule")
    assert "Commande inconnue : /bidule" in console.text


def test_run_announces_session_ignores_bom_and_closes() -> None:
    harness = Harness()
    console = Console(answers=["﻿/model haiku", "/quitter"])
    chat(harness, console).run()
    assert "Session 1" in console.text
    assert "Je passe sur Haiku 4.5." in console.text
    assert harness.brain.calls[-1] == "close"
    assert harness.brain.sent == []
