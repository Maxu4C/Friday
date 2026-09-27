"""Decide when the user starts and stops talking, from per-frame speech probabilities."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import StrEnum


class Endpoint(StrEnum):
    WAITING = "waiting"  # no speech yet
    SPEAKING = "speaking"
    DONE = "done"  # speech followed by enough silence (or maximum length reached)
    NO_SPEECH = "no_speech"  # nothing said before the start timeout


@dataclass(frozen=True)
class EndpointSettings:
    frame_seconds: float = 0.032  # 512 samples at 16 kHz
    threshold: float = 0.5
    start_timeout: float = 6.0
    end_silence: float = 1.0
    max_seconds: float = 20.0
    min_speech: float = 0.2  # consecutive speech needed to start (ignores clicks)
    preroll: float = 0.3  # audio kept from just before speech started


class Endpointer:
    def __init__(self, settings: EndpointSettings) -> None:
        self._s = settings
        frames = self._frames
        self._start_frames = max(1, frames(settings.min_speech))
        self._end_frames = max(1, frames(settings.end_silence))
        self._timeout_frames = frames(settings.start_timeout)
        self._max_frames = frames(settings.max_seconds)
        self._preroll: deque[bytes] = deque(maxlen=max(1, frames(settings.preroll)))
        self._speech: list[bytes] = []
        self._state = Endpoint.WAITING
        self._seen = 0
        self._run = 0  # consecutive speech frames while waiting
        self._silence = 0

    def _frames(self, seconds: float) -> int:
        return round(seconds / self._s.frame_seconds)

    @property
    def state(self) -> Endpoint:
        return self._state

    def push(self, frame: bytes, probability: float) -> Endpoint:
        if self._state in (Endpoint.DONE, Endpoint.NO_SPEECH):
            return self._state
        self._seen += 1
        speech = probability >= self._s.threshold
        if self._state is Endpoint.WAITING:
            self._preroll.append(frame)
            self._run = self._run + 1 if speech else 0
            if self._run >= self._start_frames:
                self._state = Endpoint.SPEAKING
                self._speech = list(self._preroll)
            elif self._seen >= self._timeout_frames:
                self._state = Endpoint.NO_SPEECH
            return self._state
        self._speech.append(frame)
        # Hysteresis: a slightly lower bar keeps soft word endings inside the utterance.
        if probability >= self._s.threshold - 0.15:
            self._silence = 0
        else:
            self._silence += 1
        if self._silence >= self._end_frames or len(self._speech) >= self._max_frames:
            self._state = Endpoint.DONE
        return self._state

    def audio(self) -> bytes:
        """The utterance, without most of the trailing silence."""
        keep = len(self._speech) - max(0, self._silence - self._frames(0.2))
        return b"".join(self._speech[:keep])
