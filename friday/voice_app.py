"""`friday ecoute`: FRIDAY always listening in the terminal — wake word, hotkey, keyboard."""

from __future__ import annotations

import signal
import sys
import threading
from collections.abc import Callable
from types import FrameType

from friday.config import FridayConfig
from friday.console import ConsoleDisplay
from friday.core.assistant import Assistant, State
from friday.runtime import build_runtime


def run_voice_app(config: FridayConfig, write: Callable[[str], None]) -> int:
    display = ConsoleDisplay(write, show_states=True)
    display.write("Chargement de FRIDAY (voix, micro, reconnaissance vocale)…\n")
    runtime = build_runtime(config, display.show, lambda text: display.write(text + "\n"))
    assistant = runtime.assistant
    info = runtime.info
    triggers = [f"dites « {info.wake_word} »"] if info.wake_word else []
    if info.hotkey:
        triggers.append(info.hotkey)
    triggers.append("Entrée")
    display.write(
        f"Pour parler : {', '.join(triggers)}. Tapez aussi vos demandes. "
        "/stop coupe la parole, /quitter pour quitter.\n"
    )
    threading.Thread(
        target=_read_keyboard, args=(assistant,), name="friday-keyboard", daemon=True
    ).start()
    previous = signal.getsignal(signal.SIGINT)

    def on_ctrl_c(_signum: int, _frame: FrameType | None) -> None:
        if assistant.state is State.IDLE:
            assistant.shutdown()
        else:
            assistant.stop()  # first Ctrl+C silences FRIDAY; when idle it quits

    signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        assistant.run()
    finally:
        signal.signal(signal.SIGINT, previous)
        runtime.close()
        display.say("À bientôt.")
        runtime.farewell()
    return 0


def _read_keyboard(assistant: Assistant) -> None:
    for raw in sys.stdin:
        line = raw.lstrip("﻿").strip()
        if line in ("/quitter", "/quit", "/q"):
            break
        if line == "/stop":
            assistant.stop()
        elif line:
            assistant.submit_text(line)
        else:
            assistant.wake("clavier")
    assistant.shutdown()
