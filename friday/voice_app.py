"""`friday ecoute`: FRIDAY always listening — wake word, global hotkey, or keyboard."""

from __future__ import annotations

import logging
import signal
import sys
import threading
from collections.abc import Callable
from types import FrameType

from friday.config import FridayConfig
from friday.console import ConsoleDisplay
from friday.core.assistant import Assistant, State
from friday.core.wake import WakeListener
from friday.factory import (
    create_controller,
    create_ears,
    create_narrator,
    create_wake_detector,
)

logger = logging.getLogger(__name__)


def run_voice_app(config: FridayConfig, write: Callable[[str], None]) -> int:
    from friday.adapters.hotkey import GlobalHotkey
    from friday.adapters.microphone import Microphone

    display = ConsoleDisplay(write, show_states=True)
    display.write("Chargement de FRIDAY (voix, micro, reconnaissance vocale)…\n")
    narrator = create_narrator(config) if config.tts.enabled else None
    microphone = Microphone(config.audio.input_device)
    microphone.start()
    ears = create_ears(config, microphone)
    assistant = Assistant(
        create_controller(config), display=display.show, ears=ears, narrator=narrator
    )

    triggers = []
    wake = config.wake_word
    if wake.enabled:
        try:
            listener = WakeListener(
                microphone.subscribe(),
                create_wake_detector(config),
                assistant,
                barge_in=wake.barge_in,
            )
            threading.Thread(target=listener.run, name="friday-wake", daemon=True).start()
            spoken_name = wake.model.replace("_", " ").title()
            triggers.append(f"dites « {spoken_name} »")
        except Exception as exc:
            logger.exception("Wake word unavailable")
            display.write(f"Mot d'activation indisponible ({exc}).\n")
    hotkey = None
    if wake.hotkey:
        try:
            hotkey = GlobalHotkey(wake.hotkey, lambda: assistant.wake("raccourci"))
            hotkey.start()
            triggers.append(wake.hotkey.title())
        except Exception as exc:
            logger.exception("Global hotkey unavailable")
            display.write(f"Raccourci {wake.hotkey} indisponible ({exc}).\n")
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
        if hotkey is not None:
            hotkey.stop()
        microphone.close()
        display.say("À bientôt.")
        if narrator is not None:
            narrator.say("À bientôt.")
            narrator.wait(timeout=10)
            narrator.close()
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
