"""Everything FRIDAY needs to run with voice: assembled once, used by the console
(`friday ecoute`) and by the HUD (`friday`)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from friday.config import FridayConfig
from friday.core.assistant import Assistant, AssistantEvent
from friday.core.controller import Controller
from friday.core.narrator import Narrator
from friday.core.wake import WakeListener
from friday.factory import create_controller, create_ears, create_narrator, create_wake_detector
from friday.ui.protocol import RuntimeInfo

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    assistant: Assistant
    controller: Controller
    narrator: Narrator | None
    info: RuntimeInfo
    _microphone: Any = None
    _hotkey: Any = None

    def close(self) -> None:
        if self._hotkey is not None:
            self._hotkey.stop()
        if self._microphone is not None:
            self._microphone.close()

    def farewell(self) -> None:
        if self.narrator is not None:
            self.narrator.say("À bientôt.")
            self.narrator.wait(timeout=10)
            self.narrator.close()


def build_runtime(
    config: FridayConfig,
    display: Callable[[AssistantEvent], None],
    report: Callable[[str], None],
) -> Runtime:
    """Load the voice, the microphone, speech recognition, the wake word and the hotkey.

    Each part degrades gracefully: FRIDAY still works (by keyboard) if one fails.
    """
    from friday.adapters.hotkey import GlobalHotkey
    from friday.adapters.microphone import Microphone

    narrator = None
    if config.tts.enabled:
        try:
            narrator = create_narrator(config)
        except Exception as exc:
            logger.exception("Voice unavailable")
            report(f"Voix indisponible ({exc}).")
    microphone: Microphone | None = Microphone(config.audio.input_device)
    ears = None
    try:
        assert microphone is not None
        microphone.start()
        ears = create_ears(config, microphone)
    except Exception as exc:
        logger.exception("Speech recognition unavailable")
        report(f"Reconnaissance vocale indisponible ({exc}) : clavier seulement.")
        if microphone is not None:
            microphone.close()
        microphone = None
    controller = create_controller(config)
    assistant = Assistant(controller, display=display, ears=ears, narrator=narrator)

    wake = config.wake_word
    wake_name = None
    if wake.enabled and microphone is not None:
        try:
            listener = WakeListener(
                microphone.subscribe(),
                create_wake_detector(config),
                assistant,
                barge_in=wake.barge_in,
            )
            threading.Thread(target=listener.run, name="friday-wake", daemon=True).start()
            wake_name = wake.model.replace("_", " ").title()
        except Exception as exc:
            logger.exception("Wake word unavailable")
            report(f"Mot d'activation indisponible ({exc}).")
    hotkey = None
    hotkey_name = None
    if wake.hotkey:
        try:
            hotkey = GlobalHotkey(wake.hotkey, lambda: assistant.wake("raccourci"))
            hotkey.start()
            hotkey_name = wake.hotkey.title()
        except Exception as exc:
            logger.exception("Global hotkey unavailable")
            report(f"Raccourci {wake.hotkey} indisponible ({exc}).")
    info = RuntimeInfo(
        voice=narrator is not None,
        microphone=microphone is not None,
        whisper=ears is not None,
        wake_word=wake_name,
        hotkey=hotkey_name,
    )
    return Runtime(assistant, controller, narrator, info, microphone, hotkey)
