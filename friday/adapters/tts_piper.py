"""Piper TTS: free, offline neural voices (https://github.com/OHF-Voice/piper1-gpl)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from friday.core.ports import AudioClip

# 5-tap binomial low-pass: takes the edge off sibilants for a softer, warmer voice.
_SOFTEN_KERNEL = np.array([1, 4, 6, 4, 1], dtype=np.float32) / 16


class PiperUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceStyle:
    length_scale: float = 1.0  # > 1: slower
    noise_scale: float = 0.667  # lower: steadier, calmer intonation
    noise_w_scale: float = 0.8  # lower: more regular rhythm
    volume: float = 1.0
    softness: float = 0.0  # 0 = raw voice, 1 = strongest high-frequency softening
    speaker: str | int | None = None  # name or id, for voices with several speakers


class PiperTTS:
    def __init__(self, models_dir: Path, voice: str, style: VoiceStyle | None = None) -> None:
        model = models_dir / f"{voice}.onnx"
        config_file = model.with_suffix(".onnx.json")
        if not model.exists() or not config_file.exists():
            raise PiperUnavailableError(
                f"Voix Piper introuvable : {model}. "
                "Lancez scripts\\install.ps1 pour la télécharger."
            )
        from piper import PiperVoice, SynthesisConfig

        style = style or VoiceStyle()
        self._voice = PiperVoice.load(model)
        self._config = SynthesisConfig(
            speaker_id=_speaker_id(config_file, style.speaker),
            length_scale=style.length_scale,
            noise_scale=style.noise_scale,
            noise_w_scale=style.noise_w_scale,
            volume=style.volume,
        )
        self._softness = min(max(style.softness, 0.0), 1.0)
        self.sample_rate = self._voice.config.sample_rate

    def synthesize(self, text: str) -> AudioClip:
        pcm = b"".join(
            chunk.audio_int16_bytes for chunk in self._voice.synthesize(text, self._config)
        )
        if self._softness > 0 and pcm:
            pcm = soften(pcm, self._softness)
        return AudioClip(pcm=pcm, sample_rate=self.sample_rate)


def soften(pcm: bytes, amount: float) -> bytes:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    filtered = np.convolve(samples, _SOFTEN_KERNEL, mode="same")
    mixed = (1 - amount) * samples + amount * filtered
    return np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()


def _speaker_id(config_file: Path, speaker: str | int | None) -> int | None:
    if speaker is None or isinstance(speaker, int):
        return speaker
    speakers = json.loads(config_file.read_text(encoding="utf-8")).get("speaker_id_map") or {}
    if speaker not in speakers:
        known = ", ".join(speakers) or "aucun"
        raise PiperUnavailableError(f"Locuteur « {speaker} » inconnu pour cette voix ({known}).")
    return int(speakers[speaker])
