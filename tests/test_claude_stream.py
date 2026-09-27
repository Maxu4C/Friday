import json
from datetime import datetime
from pathlib import Path

import pytest

from friday.adapters.claude_stream import api_retry_error, classify_error, parse_event
from friday.core.events import (
    ApiRetry,
    BrainErrorKind,
    BrainEvent,
    RateLimitStatus,
    SessionStarted,
    TextDelta,
    ToolResult,
    ToolUse,
    TurnCompleted,
)

FIXTURES = Path(__file__).parent / "fixtures" / "stream"


def load(name: str) -> list[BrainEvent]:
    events: list[BrainEvent] = []
    for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines():
        events.extend(parse_event(json.loads(line)))
    return events


def turns(events: list[BrainEvent]) -> list[list[BrainEvent]]:
    """Split events into turns, each ending with its TurnCompleted."""
    result: list[list[BrainEvent]] = [[]]
    for event in events:
        result[-1].append(event)
        if isinstance(event, TurnCompleted):
            result.append([])
    return [turn for turn in result if turn]


def text_of(turn: list[BrainEvent]) -> str:
    return "".join(e.text for e in turn if isinstance(e, TextDelta))


def test_claude_mode_has_no_tools_and_keeps_context() -> None:
    events = load("claude_mode_multiturn_model_switch.jsonl")
    init = next(e for e in events if isinstance(e, SessionStarted))
    assert init.tools == ()
    assert init.model == "claude-haiku-4-5-20251001"

    first, second, switch, fourth = turns(events)
    assert text_of(first) == "Noté."
    assert "42" in text_of(second)
    completed = [e for e in second if isinstance(e, TurnCompleted)][0]
    assert completed.error is None and completed.session_id == init.session_id


def test_model_switch_inside_the_session() -> None:
    _, _, switch, after = turns(load("claude_mode_multiturn_model_switch.jsonl"))
    assert text_of(switch).startswith("Set model to")
    assert [e for e in switch if isinstance(e, TurnCompleted)][0].error is None
    assert "claude-opus-5-5" in [e for e in after if isinstance(e, TurnCompleted)][0].models


def test_rate_limit_event_is_parsed() -> None:
    limits = [
        e
        for e in load("claude_mode_multiturn_model_switch.jsonl")
        if isinstance(e, RateLimitStatus)
    ]
    assert limits and limits[0].status == "allowed"
    assert isinstance(limits[0].resets_at, datetime)
    assert limits[0].utilization["five_hour"] == pytest.approx(0.09)


def test_interrupted_turn_is_reported_and_session_continues() -> None:
    first, interrupted, after = turns(load("interrupt.jsonl"))
    result = [e for e in interrupted if isinstance(e, TurnCompleted)][0]
    assert result.error is not None and result.error.kind is BrainErrorKind.INTERRUPTED
    assert text_of(after) == "Toujours là."


def test_code_mode_tool_calls() -> None:
    events = load("code_mode_tools.jsonl")
    init = next(e for e in events if isinstance(e, SessionStarted))
    assert init.permission_mode == "acceptEdits"
    assert [e.name for e in events if isinstance(e, ToolUse)] == ["Glob", "Bash"]
    results = [e for e in events if isinstance(e, ToolResult)]
    assert results[0].summary == "CLAUDE.md" and not results[0].is_error


def test_unknown_model_is_classified() -> None:
    events = load("unknown_model.jsonl")
    result = next(e for e in events if isinstance(e, TurnCompleted))
    assert result.error is not None and result.error.kind is BrainErrorKind.MODEL_NOT_FOUND


def test_api_retry_event() -> None:
    raw = {
        "type": "system",
        "subtype": "api_retry",
        "attempt": 1,
        "max_retries": 10,
        "retry_delay_ms": 5000,
        "error_status": 429,
        "error": "rate_limit",
    }
    [event] = parse_event(raw)
    assert event == ApiRetry(attempt=1, error="rate_limit", status=429)
    assert api_retry_error(event) is BrainErrorKind.RATE_LIMIT
    assert api_retry_error(ApiRetry(1, "server_error", 529)) is None
    assert api_retry_error(ApiRetry(1, "authentication_failed", 401)) is BrainErrorKind.AUTH


@pytest.mark.parametrize(
    ("message", "status", "kind"),
    [
        ("Rate limit reached", None, BrainErrorKind.RATE_LIMIT),
        ("anything", 429, BrainErrorKind.RATE_LIMIT),
        ("Failed to authenticate. OAuth token has expired.", None, BrainErrorKind.AUTH),
        ("unauthorized", 401, BrainErrorKind.AUTH),
        (
            "Claude Code 2.1.272 does not support this model; version 2.1.280 or newer is required",
            400,
            BrainErrorKind.MODEL_NOT_FOUND,
        ),
        ("Unable to connect to API (ENOTFOUND)", None, BrainErrorKind.NETWORK),
        ("Something odd", 500, BrainErrorKind.UNKNOWN),
    ],
)
def test_classify_error(message: str, status: int | None, kind: BrainErrorKind) -> None:
    assert classify_error(message, status) is kind


def test_unknown_lines_are_ignored() -> None:
    assert parse_event({"type": "system", "subtype": "status"}) == []
    assert parse_event({"type": "whatever"}) == []
