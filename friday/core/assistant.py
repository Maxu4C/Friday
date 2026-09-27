"""FRIDAY's state machine: IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE.

Triggers (wake word, hotkey, typed text, stop) may come from any thread; they are
queued and handled one at a time by `run()`, except `stop()` which acts at once.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from friday.core.controller import ConfirmAction, Controller, Output, Say
from friday.core.events import TextDelta, TurnCompleted
from friday.core.intents import Command
from friday.core.messages import HEARD_NOTHING, NOT_UNDERSTOOD
from friday.core.narrator import Narrator
from friday.core.ports import Ears
from friday.core.speech import Display, Segment, SpeechStream
from friday.core.voice import SpeechRouter

logger = logging.getLogger(__name__)

FOLLOW_UP_WAIT = 30.0  # max seconds to wait for FRIDAY to finish asking her question


class State(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass(frozen=True)
class StateEvent:
    state: State


@dataclass(frozen=True)
class UserSaid:
    text: str
    spoken: bool


@dataclass(frozen=True)
class ShowBlock:
    """Technical content from an [AFFICHER] block, for the screen only."""

    text: str


AssistantEvent = Output | StateEvent | UserSaid | ShowBlock


class Assistant:
    def __init__(
        self,
        controller: Controller,
        *,
        display: Callable[[AssistantEvent], None],
        ears: Ears | None = None,
        narrator: Narrator | None = None,
    ) -> None:
        self._controller = controller
        self._display = display
        self._ears = ears
        self._narrator = narrator
        self._speech = SpeechRouter(narrator) if narrator is not None else None
        self._blocks = SpeechStream()  # finds [AFFICHER] blocks, voice or not
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._state = State.IDLE
        self._busy = False  # a request is being handled (Claude may still be answering)
        # Set while FRIDAY waits for "oui"/"non" to a ConfirmAction.
        self._confirmation: queue.Queue[tuple[str, str | None]] | None = None
        if narrator is not None:
            narrator.add_listener(self._on_speaking)

    # -- triggers (any thread) ----------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    def accepts_wake(self, barge_in: bool) -> bool:
        """Should a detected wake word be acted upon now?"""
        if self._controller.mic_muted or self._state is State.LISTENING:
            return False
        return self._state is State.IDLE or barge_in

    def wake(self, source: str = "mot d'activation") -> None:
        """Listen for a request (wake word, hotkey or button). Interrupts FRIDAY if needed."""
        if self._confirmation is not None:
            return  # already listening for the answer to a confirmation
        if self._state in (State.THINKING, State.SPEAKING):
            self.stop()
        self._queue.put(("wake", source))

    def execute(self, command: Command) -> None:
        """Run a system command chosen in the interface (mode, model, session...)."""
        self._queue.put(("command", command))

    def submit_text(self, text: str) -> None:
        confirmation = self._confirmation
        if confirmation is not None:
            confirmation.put(("clavier", text))  # typed answer to "Vous confirmez ?"
        else:
            self._queue.put(("text", text))

    def stop(self) -> None:
        """Silence FRIDAY and interrupt Claude immediately."""
        confirmation = self._confirmation
        if confirmation is not None:
            confirmation.put(("stop", "non"))  # stopping during a confirmation refuses
        self._controller.interrupt()
        if self._narrator is not None:
            self._narrator.stop()
        if self._speech is not None:
            self._speech.reset()

    def shutdown(self) -> None:
        self._queue.put(("quit", ""))

    # -- main loop ----------------------------------------------------------------------

    def run(self) -> None:
        self._handle(self._controller.start(), spoken=False)
        while True:
            try:
                kind, value = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if kind == "quit":
                break
            try:
                if kind == "wake":
                    self._listen()
                elif kind == "command":
                    self._handle(self._controller.execute(value), spoken=False)
                else:
                    self._display(UserSaid(value, spoken=False))
                    self._respond(value, spoken=False)
            except Exception:
                logger.exception("Error while handling %s", kind)
                self._emit(Say("Une erreur interne est survenue, je reste à l'écoute."))
                self._busy = False
                self._set_state(State.IDLE)
        self.stop()
        self._controller.close()

    def _listen(self) -> None:
        if self._ears is None:
            return
        if self._narrator is not None:
            self._narrator.stop()  # never record FRIDAY's own voice
        self._set_state(State.LISTENING)
        heard = self._ears.listen()
        if heard.text is None:
            self._set_state(State.IDLE)
            self._emit(Say(HEARD_NOTHING if heard.reason == "silence" else NOT_UNDERSTOOD))
            return
        self._display(UserSaid(heard.text, spoken=True))
        self._respond(heard.text, spoken=True)

    def _respond(self, text: str, *, spoken: bool) -> None:
        if self._speech is not None:
            self._speech.reset()
        self._blocks = SpeechStream()
        self._handle(self._controller.handle(text), spoken=spoken)

    def _handle(self, outputs: Iterator[Output], *, spoken: bool) -> None:
        self._busy = True
        self._set_state(State.THINKING)
        try:
            for output in outputs:
                self._emit(output)
                if isinstance(output, ConfirmAction):
                    self._controller.answer_confirmation(self._await_confirmation())
        finally:
            self._busy = False
            speaking = self._narrator is not None and self._narrator.speaking
            self._set_state(State.SPEAKING if speaking else State.IDLE)
        if spoken and self._controller.awaiting_answer and self._ears is not None:
            # FRIDAY asked a question: listen for the answer without the wake word.
            if self._narrator is not None:
                self._narrator.wait(FOLLOW_UP_WAIT)
            self._queue.put(("wake", "suite"))

    def _await_confirmation(self) -> str:
        """The spoken or typed answer to a confirmation ("" if none in time)."""
        answers: queue.Queue[tuple[str, str | None]] = queue.Queue()
        self._confirmation = answers
        try:
            if self._narrator is not None:
                self._narrator.wait(FOLLOW_UP_WAIT)  # finish asking before listening
            self._set_state(State.LISTENING)
            ears = self._ears
            if ears is not None:
                threading.Thread(
                    target=lambda: answers.put(("voix", ears.listen().text)),
                    name="friday-confirmation",
                    daemon=True,
                ).start()
            try:
                source, text = answers.get(timeout=self._controller.permission_timeout)
            except queue.Empty:
                return ""
            if text and source != "stop":
                self._display(UserSaid(text, spoken=source == "voix"))
            return text or ""
        finally:
            self._confirmation = None
            self._set_state(State.THINKING)

    def _emit(self, output: Output) -> None:
        self._display(output)
        if self._speech is not None:
            self._speech.handle(output)
        segments: list[Segment] = []
        if isinstance(output, TextDelta):
            segments = self._blocks.feed(output.text)
        elif isinstance(output, TurnCompleted):
            segments = self._blocks.flush()
        for segment in segments:
            if isinstance(segment, Display) and segment.text.strip():
                self._display(ShowBlock(segment.text))

    # -- state ------------------------------------------------------------------------

    def _on_speaking(self, speaking: bool) -> None:
        if speaking and self._state in (State.IDLE, State.THINKING):
            self._set_state(State.SPEAKING)
        elif not speaking and self._state is State.SPEAKING:
            self._set_state(State.THINKING if self._busy else State.IDLE)

    def _set_state(self, state: State) -> None:
        with self._lock:
            if state is self._state:
                return
            self._state = state
        self._display(StateEvent(state))
