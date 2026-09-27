"""Piper TTS: free, offline neural voices (https://github.com/OHF-Voice/piper1-gpl)."""

from __future__ import annotations

from pathlib import Path

from friday.core.ports import AudioClip


class PiperUnavailableError(RuntimeError):
    pass


class PiperTTS:
    def __init__(self, models_dir: Path, voice: str, length_scale: float = 1.0) -> None:
        model = models_dir / f"{voice}.onnx"
        if not model.exists() or not model.with_suffix(".onnx.json").exists():
            raise PiperUnavailableError(
                f"Voix Piper introuvable : {model}. "
                "Lancez scripts\\install.ps1 pour la télécharger."
            )
        from piper import PiperVoice, SynthesisConfig

        self._voice = PiperVoice.load(model)
        self._config = SynthesisConfig(length_scale=length_scale)
        self.sample_rate = self._voice.config.sample_rate

    def synthesize(self, text: str) -> AudioClip:
        pcm = b"".join(
            chunk.audio_int16_bytes for chunk in self._voice.synthesize(text, self._config)
        )
        return AudioClip(pcm=pcm, sample_rate=self.sample_rate)
