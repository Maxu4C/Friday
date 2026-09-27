"""Test doubles for the core ports."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from friday.core.events import (
    BrainError,
    BrainEvent,
    Mode,
    PermissionRequest,
    RateLimitStatus,
    TextDelta,
    TurnCompleted,
)
from friday.core.ports import SessionState

Reply = Callable[[str, SessionState], list[BrainEvent]]


def answer(*chunks: str, error: BrainError | None = None) -> Reply:
    def reply(_: str, state: SessionState) -> list[BrainEvent]:
        events: list[BrainEvent] = [TextDelta(chunk) for chunk in chunks]
        events.append(TurnCompleted("".join(chunks), state.session_id, error=error))
        return events

    return reply


def needs_permission(tool: str, tool_input: dict[str, Any], description: str = "") -> Reply:
    """Claude asks for `tool`; then says "Fait." if allowed, "Refusé." otherwise."""

    def reply(_: str, state: SessionState) -> list[Any]:
        def outcome(allowed: bool) -> list[BrainEvent]:
            text = "Fait." if allowed else "Refusé."
            return [TextDelta(text), TurnCompleted(text, state.session_id)]

        return [PermissionRequest("req-1", tool, tool_input, description), outcome]

    return reply  # type: ignore[return-value]


class FakeBrain:
    """Records what the controller asks; replies with scripted events."""

    def __init__(self, replies: list[Reply] | None = None) -> None:
        self._state = SessionState(Mode.CLAUDE, "opus", "initial")
        self.replies = list(replies or [])
        self.sent: list[tuple[str, str, Mode]] = []  # (text, model, mode)
        self.calls: list[str] = []
        self.permissions: list[tuple[str, bool, str]] = []  # (tool, allowed, message)
        self.last_rate_limit: RateLimitStatus | None = None
        self._pending: list[Any] = []
        self._ids = iter(f"sid-{n}" for n in range(1, 1000))

    @property
    def state(self) -> SessionState:
        return self._state

    def send(self, text: str) -> None:
        if self._state.session_id is None:
            self._state.session_id = next(self._ids)
        self.sent.append((text, self._state.model, self._state.mode))
        reply = self.replies.pop(0) if self.replies else answer(f"Réponse à : {text}")
        self._pending = reply(text, self._state)

    def events(self) -> Iterator[BrainEvent]:
        while self._pending:
            item = self._pending.pop(0)
            if callable(item):  # continuation that depends on the permission decision
                self._pending = list(item(self.permissions[-1][1])) + self._pending
                continue
            yield item

    def respond_permission(
        self, request: PermissionRequest, allow: bool, message: str = ""
    ) -> None:
        self.permissions.append((request.tool, allow, message))

    def interrupt(self) -> None:
        self.calls.append("interrupt")
        if self._pending:
            self._pending = [TurnCompleted("", self._state.session_id)]

    def set_model(self, alias: str) -> None:
        self.calls.append(f"model:{alias}")
        self._state.model = alias

    def set_mode(self, mode: Mode) -> None:
        self.calls.append(f"mode:{mode.value}")
        self._state.mode = mode

    def new_session(self, name: str, mode: Mode, model: str, workspace: Path | None = None) -> None:
        self.calls.append(f"new:{name}")
        self._state = SessionState(mode, model, name, None, workspace)

    def resume_session(
        self, session_id: str, name: str, mode: Mode, model: str, workspace: Path | None = None
    ) -> None:
        self.calls.append(f"resume:{session_id}")
        self._state = SessionState(mode, model, name, session_id, workspace)

    def close(self) -> None:
        self.calls.append("close")


class MemoryStore:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = copy.deepcopy(data)
        self.saves = 0

    def load(self) -> dict[str, Any] | None:
        return copy.deepcopy(self.data)

    def save(self, data: dict[str, Any]) -> None:
        self.data = copy.deepcopy(data)
        self.saves += 1
