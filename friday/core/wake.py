"""Watch the microphone for the wake word and wake the assistant.

Anti-echo: while FRIDAY listens to a request the detector is not fed, and right
after she stops speaking it stays deaf for a moment (echo tail from speakers).
While she speaks, the wake word still works (barge-in): saying it interrupts her.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import Protocol

from friday.core.assistant import State

logger = logging.getLogger(__name__)


class WakeWordDetector(Protocol):
    def push(self, frame: bytes) -> bool:
        """Feed one 512-sample frame (16 kHz, int16); True when the wake word is heard."""

    def reset(self) -> None: ...


class WakeTarget(Protocol):
    @property
    def state(self) -> State: ...

    def accepts_wake(self, barge_in: bool) -> bool: ...

    def wake(self, source: str = ...) -> None: ...


class WakeListener:
    def __init__(
        self,
        frames: Iterable[bytes],
        detector: WakeWordDetector,
        assistant: WakeTarget,
        *,
        barge_in: bool = True,
        echo_tail: float = 0.6,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._frames = frames
        self._detector = detector
        self._assistant = assistant
        self._barge_in = barge_in
        self._echo_tail = echo_tail
        self._clock = clock
        self.detections = 0

    def run(self) -> None:
        feeding = False
        deaf_until = 0.0
        previous = self._assistant.state
        for frame in self._frames:
            state = self._assistant.state
            if previous is State.SPEAKING and state is not State.SPEAKING:
                deaf_until = self._clock() + self._echo_tail
            previous = state
            if not self._assistant.accepts_wake(self._barge_in) or self._clock() < deaf_until:
                feeding = False
                continue
            if not feeding:
                self._detector.reset()  # forget audio heard while not listening
                feeding = True
            if self._detector.push(frame):
                self.detections += 1
                logger.info("Wake word detected (state %s)", state)
                self._detector.reset()
                self._assistant.wake("mot d'activation")
