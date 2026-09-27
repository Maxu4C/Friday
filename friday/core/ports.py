"""Interfaces between the core and its adapters."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from friday.core.events import BrainEvent, Mode, RateLimitStatus


@dataclass
class SessionState:
    mode: Mode
    model: str
    name: str
    session_id: str | None = None
    workspace: Path | None = None  # None: the default working folder


class BrainBusyError(RuntimeError):
    """A request is already running."""


@dataclass(frozen=True)
class AudioClip:
    pcm: bytes  # signed 16-bit little-endian samples
    sample_rate: int
    channels: int = 1

    @property
    def duration(self) -> float:
        return len(self.pcm) / (2 * self.channels * self.sample_rate)


class TextToSpeech(Protocol):
    def synthesize(self, text: str) -> AudioClip: ...


class AudioOutput(Protocol):
    def play(self, clip: AudioClip, cancelled: Callable[[], bool]) -> None:
        """Play until the end, or stop as soon as `cancelled()` becomes true."""


class SpeechToText(Protocol):
    def transcribe(self, clip: AudioClip) -> str: ...


class VoiceActivityDetector(Protocol):
    """Probability that a 512-sample, 16 kHz frame contains speech."""

    def reset(self) -> None: ...

    def probability(self, frame: bytes) -> float: ...


@dataclass(frozen=True)
class Heard:
    text: str | None  # None: nothing usable
    reason: str = ""  # "silence" (nobody spoke) or "incompris" (speech, but no usable text)


class Ears(Protocol):
    """Listen for one utterance (push-to-talk or after the wake word) and transcribe it."""

    def listen(self) -> Heard: ...


class Storage(Protocol):
    """Persistence of a small JSON document (sessions, usage)."""

    def load(self) -> dict[str, Any] | None: ...

    def save(self, data: dict[str, Any]) -> None: ...


class Brain(Protocol):
    @property
    def state(self) -> SessionState: ...

    @property
    def last_rate_limit(self) -> RateLimitStatus | None: ...

    def send(self, text: str) -> None:
        """Start a request; read its events with `events()`."""

    def events(self) -> Iterator[BrainEvent]:
        """Events of the running request, ending with a TurnCompleted.

        Safe to call again after the consumer was interrupted (e.g. Ctrl+C).
        """

    def interrupt(self) -> None: ...

    def set_model(self, alias: str) -> None: ...

    def set_mode(self, mode: Mode) -> None: ...

    def new_session(
        self, name: str, mode: Mode, model: str, workspace: Path | None = None
    ) -> None: ...

    def resume_session(
        self, session_id: str, name: str, mode: Mode, model: str, workspace: Path | None = None
    ) -> None: ...

    def close(self) -> None: ...
