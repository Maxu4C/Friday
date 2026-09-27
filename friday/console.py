"""Terminal display of FRIDAY's outputs (shared by `friday chat` and `friday ecoute`)."""

from __future__ import annotations

import threading
from collections.abc import Callable

from friday.core.assistant import AssistantEvent, State, StateEvent, UserSaid
from friday.core.controller import Ask, Say, ShowSessions, StateChanged, StopSpeaking
from friday.core.events import TextDelta, ToolResult, ToolUse, TurnCompleted
from friday.core.messages import MODE_LABELS

_STATE_LINES = {
    State.LISTENING: "  [écoute… parlez]",
    State.THINKING: "  [réflexion…]",
}


class ConsoleDisplay:
    """Thread-safe: the wake word, hotkey and keyboard threads may all print."""

    def __init__(self, write: Callable[[str], None], *, show_states: bool = False) -> None:
        self._write = write
        self._show_states = show_states
        self._streaming = False
        self._lock = threading.RLock()

    def show(self, event: AssistantEvent) -> None:
        with self._lock:
            self._show(event)

    def say(self, text: str) -> None:
        with self._lock:
            self.end_stream()
            self._write(f"\nFRIDAY > {text}\n")

    def write(self, text: str) -> None:
        with self._lock:
            self.end_stream()
            self._write(text)

    def end_stream(self) -> None:
        with self._lock:
            if self._streaming:
                self._write("\n")
                self._streaming = False

    def _show(self, event: AssistantEvent) -> None:
        if isinstance(event, TextDelta):
            if not self._streaming:
                self._write("\nFRIDAY > ")
                self._streaming = True
            self._write(event.text)
        elif isinstance(event, ToolUse):
            self.end_stream()
            self._write(f"  [outil] {event.name} {_brief(event.input)}\n")
        elif isinstance(event, ToolResult) and event.is_error:
            self._write(f"  [échec] {event.summary}\n")
        elif isinstance(event, TurnCompleted):
            self.end_stream()
            if event.permission_denials:
                self._write(f"  [refusé] {', '.join(event.permission_denials)}\n")
        elif isinstance(event, Say | Ask):
            self.say(event.text)
        elif isinstance(event, ShowSessions):
            self.end_stream()
            for record in event.sessions:
                mark = "*" if record.key == event.current_key else " "
                lock = record.model_lock or "auto"
                used = record.last_used_at.strftime("%d/%m %H:%M")
                line = f"  {mark} {record.name} · {MODE_LABELS[record.mode]} · {lock} · {used}"
                self._write(line + (f" · {record.summary}" if record.summary else "") + "\n")
        elif isinstance(event, UserSaid):
            self.end_stream()
            self._write(f"\nVous ({'voix' if event.spoken else 'clavier'}) > {event.text}\n")
        elif isinstance(event, StateEvent):
            state_line = _STATE_LINES.get(event.state)
            if self._show_states and state_line:
                self.end_stream()
                self._write(state_line + "\n")
        elif isinstance(event, StateChanged | StopSpeaking):
            pass  # the HUD uses StateChanged; changes are also announced with Say


def _brief(data: dict[str, object], limit: int = 80) -> str:
    for key in ("command", "file_path", "pattern", "path", "url"):
        if key in data:
            text = str(data[key])
            return text if len(text) <= limit else text[: limit - 1] + "…"
    return ""
