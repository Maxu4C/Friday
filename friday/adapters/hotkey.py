"""Global keyboard shortcut (works even when FRIDAY's window is not focused)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_MODIFIERS = {"ctrl", "alt", "shift", "cmd", "win", "alt_gr"}


def to_pynput(combo: str) -> str:
    """ "ctrl+alt+f" -> "<ctrl>+<alt>+f" (pynput's GlobalHotKeys syntax)."""
    keys = []
    for key in combo.lower().replace(" ", "").split("+"):
        key = "cmd" if key == "win" else key
        keys.append(f"<{key}>" if key in _MODIFIERS or len(key) > 1 else key)
    return "+".join(keys)


class GlobalHotkey:
    def __init__(self, combo: str, callback: Callable[[], None]) -> None:
        self._combo = to_pynput(combo)
        self._callback = callback
        self._listener: Any = None

    def start(self) -> None:
        from pynput import keyboard

        self._listener = keyboard.GlobalHotKeys({self._combo: self._fire})
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()

    def _fire(self) -> None:
        try:
            self._callback()
        except Exception:
            logger.exception("Hotkey callback failed")
