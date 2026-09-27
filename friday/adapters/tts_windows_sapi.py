"""Fallback voice: the speech engine built into Windows (SAPI), through pyttsx3."""

from __future__ import annotations

import logging
import tempfile
import wave
from pathlib import Path
from typing import Any

from friday.core.ports import AudioClip

logger = logging.getLogger(__name__)


class WindowsSapiTTS:
    """Must be used from a single thread (the narrator's synthesis thread)."""

    def __init__(self, rate: int = 185) -> None:
        self._rate = rate
        self._engine: Any = None

    def synthesize(self, text: str) -> AudioClip:
        engine = self._get_engine()
        with tempfile.TemporaryDirectory(prefix="friday-sapi-") as folder:
            path = Path(folder) / "phrase.wav"
            engine.save_to_file(text, str(path))
            engine.runAndWait()
            with wave.open(str(path), "rb") as wav:
                return AudioClip(
                    pcm=wav.readframes(wav.getnframes()),
                    sample_rate=wav.getframerate(),
                    channels=wav.getnchannels(),
                )

    def _get_engine(self) -> Any:
        if self._engine is None:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", self._rate)
            french = [
                voice
                for voice in engine.getProperty("voices")
                if "fr" in f"{voice.id} {voice.name} {voice.languages}".casefold()
            ]
            if french:
                engine.setProperty("voice", french[0].id)
            else:
                logger.warning("No French Windows voice installed; using the default one")
            self._engine = engine
        return self._engine
