"""Speech to text with faster-whisper, locally, on the NVIDIA GPU when available."""

from __future__ import annotations

import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from friday.core.ports import AudioClip

logger = logging.getLogger(__name__)

WHISPER_RATE = 16000
# Segments Whisper itself flags as probably not speech.
_NO_SPEECH_PROB = 0.6
_MIN_LOGPROB = -1.0


def enable_cuda_libraries() -> None:
    """Make the cuBLAS / cuDNN DLLs installed by pip visible to CTranslate2 (Windows)."""
    for package in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_nvrtc"):
        try:
            spec = importlib.util.find_spec(package)
        except ModuleNotFoundError:
            continue
        for base in (spec.submodule_search_locations or []) if spec else []:
            folder = os.path.join(base, "bin")
            if os.path.isdir(folder):
                os.add_dll_directory(folder)
                os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")


def download(model: str, models_dir: Path) -> None:
    """Fetch the model once into models/whisper (used by install.ps1)."""
    from faster_whisper import download_model

    download_model(model, cache_dir=str(models_dir))


class FasterWhisperSTT:
    def __init__(
        self,
        model: str,
        models_dir: Path,
        *,
        device: str = "cuda",
        compute_type: str = "float16",
        initial_prompt: str = "",
        beam_size: int = 5,
    ) -> None:
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        enable_cuda_libraries()
        self.device = device
        self._initial_prompt = initial_prompt or None
        self._beam_size = beam_size
        self._model = self._load(model, models_dir, compute_type)

    def _load(self, model: str, models_dir: Path, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        def load(device: str, compute_type: str) -> Any:
            try:  # offline first: no network call once the model is downloaded
                return WhisperModel(
                    model, device=device, compute_type=compute_type,
                    download_root=str(models_dir), local_files_only=True,
                )  # fmt: skip
            except Exception:
                logger.info("Whisper model %s not cached, downloading it", model)
                return WhisperModel(
                    model, device=device, compute_type=compute_type,
                    download_root=str(models_dir),
                )  # fmt: skip

        try:
            return load(self.device, compute_type)
        except Exception as exc:
            if self.device == "cpu":
                raise
            logger.warning("Whisper on %s failed (%s), falling back to CPU", self.device, exc)
            self.device = "cpu"
            return load("cpu", "int8")

    def transcribe(self, clip: AudioClip) -> str:
        audio = _to_whisper_audio(clip)
        if len(audio) == 0:
            return ""
        segments, _ = self._model.transcribe(
            audio,
            language="fr",
            beam_size=self._beam_size,
            initial_prompt=self._initial_prompt,
            condition_on_previous_text=False,
            vad_filter=False,  # the recorder already cut the utterance
        )
        kept = [
            segment.text.strip()
            for segment in segments
            if not (segment.no_speech_prob > _NO_SPEECH_PROB and segment.avg_logprob < _MIN_LOGPROB)
        ]
        return " ".join(text for text in kept if text)


def _to_whisper_audio(clip: AudioClip) -> np.ndarray:
    samples = np.frombuffer(clip.pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if clip.channels > 1:
        samples = samples.reshape(-1, clip.channels).mean(axis=1)
    if clip.sample_rate != WHISPER_RATE and len(samples):
        count = int(len(samples) * WHISPER_RATE / clip.sample_rate)
        samples = np.interp(
            np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples
        ).astype(np.float32)
    return samples
