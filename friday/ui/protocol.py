"""JSON messages between FRIDAY and the HUD (WebSocket), in both directions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from friday.core.assistant import AssistantEvent, ShowBlock, StateEvent, UserSaid
from friday.core.controller import (
    Ask,
    ConfirmAction,
    Controller,
    Say,
    ShowSessions,
    StateChanged,
    StopSpeaking,
)
from friday.core.events import (
    Mode,
    RateLimitStatus,
    TextDelta,
    ToolResult,
    ToolUse,
    TurnCompleted,
)
from friday.core.intents import (
    AutoModel,
    Command,
    ForgetSession,
    MuteMic,
    NewSession,
    RenameSession,
    ResumeSession,
    SetMode,
    SetModel,
    UnmuteMic,
)

REFRESH = {"type": "refresh"}  # the server answers with a fresh snapshot


@dataclass(frozen=True)
class RuntimeInfo:
    """What is running, for the HUD indicators."""

    voice: bool
    microphone: bool
    whisper: bool
    wake_word: str | None
    hotkey: str | None


def event_message(event: AssistantEvent) -> dict[str, Any] | None:
    if isinstance(event, TextDelta):
        return {"type": "delta", "text": event.text}
    if isinstance(event, ToolUse):
        return {"type": "tool", "name": event.name, "detail": _brief(event.input)}
    if isinstance(event, ToolResult):
        return {"type": "tool_error", "summary": event.summary} if event.is_error else None
    if isinstance(event, TurnCompleted):
        return {
            "type": "turn_done",
            "error": event.error.kind.value if event.error else None,
            "denied": list(event.permission_denials),
        }
    if isinstance(event, Say):
        return {"type": "say", "text": event.text}
    if isinstance(event, Ask):
        return {"type": "ask", "text": event.text}
    if isinstance(event, ConfirmAction):
        return {
            "type": "confirm",
            "question": event.question,
            "detail": event.detail,
            "dangerous": event.dangerous,
            "step": event.step,
        }
    if isinstance(event, StateEvent):
        return {"type": "state", "state": event.state.value}
    if isinstance(event, UserSaid):
        return {"type": "user", "text": event.text, "spoken": event.spoken}
    if isinstance(event, ShowBlock):
        return {"type": "block", "text": event.text}
    if isinstance(event, StopSpeaking):
        return {"type": "stopped"}
    if isinstance(event, StateChanged | ShowSessions | RateLimitStatus):
        return REFRESH
    return None


def snapshot(controller: Controller, info: RuntimeInfo, state: str) -> dict[str, Any]:
    current = controller.current
    labels = dict(controller.model_choices)
    limit = controller.rate_limit
    return {
        "type": "snapshot",
        "state": state,
        "session": {
            "key": current.key,
            "name": current.name,
            "mode": current.mode.value,
            "model": controller.active_model,
            "model_label": labels.get(controller.active_model, controller.active_model),
            "locked": current.model_lock,
            "workspace": current.workspace,
        },
        "sessions": [
            {
                "key": record.key,
                "name": record.name,
                "mode": record.mode.value,
                "model": record.model_lock or "auto",
                "last_used": record.last_used_at.isoformat(timespec="minutes"),
                "summary": record.summary,
            }
            for record in controller.sessions
        ],
        "models": [{"alias": alias, "label": label} for alias, label in controller.model_choices],
        "usage": controller.usage_today(),
        "quota": {k: round(v * 100) for k, v in limit.utilization.items()} if limit else {},
        "indicators": {
            "voice": info.voice,
            "microphone": info.microphone and not controller.mic_muted,
            "mic_muted": controller.mic_muted,
            "whisper": info.whisper,
            "wake_word": info.wake_word,
            "hotkey": info.hotkey,
        },
    }


def client_action(message: Any, models: set[str]) -> tuple[str, Any] | None:
    """What a HUD message asks for: ("text", str), ("wake", None), ("stop", None) or
    ("command", Command). None for anything malformed."""
    if not isinstance(message, dict):
        return None
    kind = message.get("type")
    value = message.get("value")
    text = value.strip() if isinstance(value, str) else ""
    if kind == "text":
        return ("text", text[:4000]) if text else None
    if kind == "ptt":
        return ("wake", None)
    if kind == "stop":
        return ("stop", None)
    command: Command | None = None
    if kind == "mode" and text in {m.value for m in Mode}:
        command = SetMode(Mode(text))
    elif kind == "model":
        command = AutoModel() if text == "auto" else SetModel(text) if text in models else None
    elif kind == "session_new":
        command = NewSession(text[:80] or None)
    elif kind == "session_resume" and text:
        command = ResumeSession(text)
    elif kind == "session_rename" and text:
        command = RenameSession(text[:80])
    elif kind == "session_forget" and text:
        command = ForgetSession(text)
    elif kind == "mute":
        command = MuteMic()
    elif kind == "unmute":
        command = UnmuteMic()
    return ("command", command) if command is not None else None


def _brief(data: dict[str, object], limit: int = 160) -> str:
    for key in ("command", "file_path", "pattern", "path", "url", "query"):
        if key in data:
            text = str(data[key])
            return text if len(text) <= limit else text[: limit - 1] + "…"
    return ""


def saved_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The HUD history as kept between launches: consecutive text fragments merged,
    confirmations dropped (their question died with the previous run)."""
    kept: list[dict[str, Any]] = []
    for message in messages:
        kind = message.get("type")
        if kind in ("confirm", "stopped", "state", "snapshot"):
            continue
        if kind == "delta" and kept and kept[-1].get("type") == "delta":
            kept[-1] = {"type": "delta", "text": kept[-1]["text"] + str(message.get("text", ""))}
            continue
        kept.append(dict(message))
    return kept
