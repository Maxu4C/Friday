"""Translate `claude -p --output-format stream-json` lines into brain events.

Formats observed on Claude Code 2.1.283 (see tests/fixtures/stream/).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from friday.core.events import (
    ApiRetry,
    BrainError,
    BrainErrorKind,
    BrainEvent,
    PermissionRequest,
    RateLimitStatus,
    SessionStarted,
    TextDelta,
    ToolResult,
    ToolUse,
    TurnCompleted,
)

_SYNTHETIC_MODEL = "<synthetic>"
_SUMMARY_LENGTH = 200

_AUTH_HINTS = ("authenticat", "oauth", "/login", "log in", "logged out", "credentials")
_MODEL_HINTS = (
    "selected model",
    "does not support this model",
    "model_not_found",
    "not_found_error",
)
_RATE_HINTS = ("rate limit", "rate_limit", "usage limit", "limit reached", "quota")
_NETWORK_HINTS = ("connect", "network", "enotfound", "econnrefused", "econnreset", "fetch failed")


def parse_event(raw: dict[str, Any]) -> list[BrainEvent]:
    kind = raw.get("type")
    if kind == "system":
        return _parse_system(raw)
    if kind == "stream_event":
        return _parse_stream_event(raw.get("event") or {})
    if kind == "assistant":
        return _parse_assistant(raw.get("message") or {})
    if kind == "user":
        return _parse_tool_results(raw.get("message") or {})
    if kind == "rate_limit_event":
        return [_parse_rate_limit(raw.get("rate_limit_info") or {})]
    if kind == "result":
        return [_parse_result(raw)]
    if kind == "control_request":
        request = raw.get("request") or {}
        if request.get("subtype") == "can_use_tool":
            return [
                PermissionRequest(
                    request_id=str(raw.get("request_id", "")),
                    tool=str(request.get("tool_name", "")),
                    input=dict(request.get("input") or {}),
                    description=str(request.get("description") or ""),
                )
            ]
    return []


def classify_error(message: str, status: int | None) -> BrainErrorKind:
    text = message.casefold()
    if status == 429 or any(hint in text for hint in _RATE_HINTS):
        return BrainErrorKind.RATE_LIMIT
    if status in (401, 403) or any(hint in text for hint in _AUTH_HINTS):
        return BrainErrorKind.AUTH
    if status == 404 or any(hint in text for hint in _MODEL_HINTS):
        return BrainErrorKind.MODEL_NOT_FOUND
    if any(hint in text for hint in _NETWORK_HINTS):
        return BrainErrorKind.NETWORK
    return BrainErrorKind.UNKNOWN


def api_retry_error(retry: ApiRetry) -> BrainErrorKind | None:
    """Retries FRIDAY must stop instead of letting claude loop on them."""
    error = (retry.error or "").casefold()
    if error == "rate_limit" or retry.status == 429:
        return BrainErrorKind.RATE_LIMIT
    if error == "authentication_failed" or retry.status in (401, 403):
        return BrainErrorKind.AUTH
    if "connect" in error or "network" in error:
        return BrainErrorKind.NETWORK
    return None


def _parse_system(raw: dict[str, Any]) -> list[BrainEvent]:
    subtype = raw.get("subtype")
    if subtype == "init":
        return [
            SessionStarted(
                session_id=str(raw.get("session_id", "")),
                model=str(raw.get("model", "")),
                tools=tuple(raw.get("tools") or ()),
                permission_mode=str(raw.get("permissionMode", "")),
            )
        ]
    if subtype == "api_retry":
        status = raw.get("error_status")
        return [
            ApiRetry(
                attempt=int(raw.get("attempt") or 0),
                error=raw.get("error"),
                status=int(status) if isinstance(status, int) else None,
            )
        ]
    return []


def _parse_stream_event(event: dict[str, Any]) -> list[BrainEvent]:
    if event.get("type") != "content_block_delta":
        return []
    delta = event.get("delta") or {}
    if delta.get("type") == "text_delta" and delta.get("text"):
        return [TextDelta(delta["text"])]
    return []


def _parse_assistant(message: dict[str, Any]) -> list[BrainEvent]:
    events: list[BrainEvent] = []
    synthetic = message.get("model") == _SYNTHETIC_MODEL
    for block in message.get("content") or []:
        if block.get("type") == "tool_use":
            events.append(
                ToolUse(
                    tool_id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    input=dict(block.get("input") or {}),
                )
            )
        elif synthetic and block.get("type") == "text" and block.get("text"):
            # Synthetic replies (slash commands, local errors) are not streamed as deltas.
            events.append(TextDelta(block["text"]))
    return events


def _parse_tool_results(message: dict[str, Any]) -> list[BrainEvent]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        ToolResult(
            tool_id=str(block.get("tool_use_id", "")),
            is_error=bool(block.get("is_error", False)),
            summary=_summarize(block.get("content")),
        )
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]


def _summarize(content: Any) -> str:
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    text = " ".join(str(content or "").split())
    return text if len(text) <= _SUMMARY_LENGTH else text[: _SUMMARY_LENGTH - 1] + "…"


def _parse_rate_limit(info: dict[str, Any]) -> RateLimitStatus:
    windows = info.get("unifiedWindows") or {}
    return RateLimitStatus(
        status=str(info.get("status", "")),
        resets_at=_timestamp(info.get("resetsAt")),
        utilization={
            name: float(window["utilization"])
            for name, window in windows.items()
            if isinstance(window, dict) and "utilization" in window
        },
    )


def _parse_result(raw: dict[str, Any]) -> TurnCompleted:
    text = raw.get("result")
    text = text if isinstance(text, str) else ""
    error: BrainError | None = None
    if raw.get("subtype") == "error_during_execution":
        interrupted = raw.get("terminal_reason") == "aborted_streaming"
        kind = BrainErrorKind.INTERRUPTED if interrupted else BrainErrorKind.UNKNOWN
        error = BrainError(kind, "; ".join(raw.get("errors") or ()))
    elif raw.get("is_error"):
        status = raw.get("api_error_status")
        status = status if isinstance(status, int) else None
        error = BrainError(classify_error(text, status), text)
    denials = tuple(
        str(denial.get("tool_name", "")) if isinstance(denial, dict) else str(denial)
        for denial in raw.get("permission_denials") or ()
    )
    return TurnCompleted(
        text=text,
        session_id=raw.get("session_id"),
        models=tuple((raw.get("modelUsage") or {}).keys()),
        error=error,
        permission_denials=denials,
    )


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, int | float) and value > 0:
        return datetime.fromtimestamp(value, tz=UTC)
    return None
