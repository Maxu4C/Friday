"""Interfaces between the core and its adapters."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from friday.core.events import BrainEvent, Mode, RateLimitStatus


@dataclass
class SessionState:
    mode: Mode
    model: str
    name: str
    session_id: str | None = None


class BrainBusyError(RuntimeError):
    """A request is already running."""


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

    def new_session(self, name: str, mode: Mode, model: str) -> None: ...

    def resume_session(self, session_id: str, name: str, mode: Mode, model: str) -> None: ...

    def close(self) -> None: ...
