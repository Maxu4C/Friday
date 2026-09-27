"""Events emitted by the brain while it answers a request."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Mode(StrEnum):
    CLAUDE = "claude"  # conversation only, no tools
    CLAUDE_CODE = "claude_code"  # agent acting on the computer


class BrainErrorKind(StrEnum):
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    MODEL_NOT_FOUND = "model_not_found"
    NETWORK = "network"
    INTERRUPTED = "interrupted"
    TIMEOUT = "timeout"
    PROCESS_DIED = "process_died"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BrainError:
    kind: BrainErrorKind
    message: str = ""
    resets_at: datetime | None = None


@dataclass(frozen=True)
class SessionStarted:
    session_id: str
    model: str
    tools: tuple[str, ...]
    permission_mode: str


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolUse:
    tool_id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    is_error: bool
    summary: str


@dataclass(frozen=True)
class RateLimitStatus:
    status: str  # "allowed", "allowed_warning" or "rejected"
    resets_at: datetime | None
    utilization: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ApiRetry:
    attempt: int
    error: str | None
    status: int | None


@dataclass(frozen=True)
class PermissionRequest:
    """Claude Code asks whether it may run a tool; answer with Brain.respond_permission."""

    request_id: str
    tool: str
    input: dict[str, Any]
    description: str = ""


@dataclass(frozen=True)
class TurnCompleted:
    text: str
    session_id: str | None
    models: tuple[str, ...] = ()
    error: BrainError | None = None
    permission_denials: tuple[str, ...] = ()


BrainEvent = (
    SessionStarted | TextDelta | ToolUse | ToolResult | RateLimitStatus | ApiRetry
    | PermissionRequest | TurnCompleted
)  # fmt: skip
