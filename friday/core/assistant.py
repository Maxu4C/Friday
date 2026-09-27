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

from friday.core.controller import Controller, Output, Say
from friday.core.messages import HEARD_NOTHING, NOT_UNDERSTOOD
from friday.core.narrator import Narrator
from friday.core.ports import Ears
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


AssistantEvent = Output | StateEvent | UserSaid


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
        self._queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._lock = threading.Lock()
        self._state = State.IDLE
        self._busy = False  # a request is being handled (Claude may still be answering)
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
        if self._state in (State.THINKING, State.SPEAKING):
            self.stop()
        self._queue.put(("wake", source))

    def submit_text(self, text: str) -> None:
        self._queue.put(("text", text))

    def stop(self) -> None:
        """Silence FRIDAY and interrupt Claude immediately."""
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
        self._handle(self._controller.handle(text), spoken=spoken)

    def _handle(self, outputs: Iterator[Output], *, spoken: bool) -> None:
        self._busy = True
        self._set_state(State.THINKING)
        try:
            for output in outputs:
                self._emit(output)
        finally:
            self._busy = False
            speaking = self._narrator is not None and self._narrator.speaking
            self._set_state(State.SPEAKING if speaking else State.IDLE)
        if spoken and self._controller.awaiting_answer and self._ears is not None:
            # FRIDAY asked a question: listen for the answer without the wake word.
            if self._narrator is not None:
                self._narrator.wait(FOLLOW_UP_WAIT)
            self._queue.put(("wake", "suite"))

    def _emit(self, output: Output) -> None:
        self._display(output)
        if self._speech is not None:
            self._speech.handle(output)  # display blocks are already shown with the text

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
