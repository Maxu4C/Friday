"""Wake word with openWakeWord (free, offline, CPU): "hey Jarvis" until a "Friday" model
is trained (phase 10); any .onnx wake word model placed in models/openwakeword works."""

from __future__ import annotations

from pathlib import Path

import numpy as np

CHUNK_SAMPLES = 1280  # openWakeWord works on 80 ms chunks at 16 kHz


class WakeWordUnavailableError(RuntimeError):
    pass


class OpenWakeWordDetector:
    def __init__(self, models_dir: Path, model: str, threshold: float = 0.5) -> None:
        candidates = sorted(models_dir.glob(f"{model}*.onnx"))
        features = [models_dir / "melspectrogram.onnx", models_dir / "embedding_model.onnx"]
        if not candidates or not all(path.exists() for path in features):
            raise WakeWordUnavailableError(
                f"Modèle de mot d'activation « {model} » introuvable dans {models_dir}. "
                "Lancez scripts\\install.ps1."
            )
        from openwakeword import Model

        self._model = Model(
            wakeword_models=[str(candidates[0])],
            inference_framework="onnx",
            melspec_model_path=str(features[0]),
            embedding_model_path=str(features[1]),
        )
        self._name = next(iter(self._model.models))
        self._threshold = threshold
        self._buffer = np.zeros(0, dtype=np.int16)
        self.last_score = 0.0

    def push(self, frame: bytes) -> bool:
        self._buffer = np.concatenate([self._buffer, np.frombuffer(frame, dtype=np.int16)])
        detected = False
        while len(self._buffer) >= CHUNK_SAMPLES:
            chunk, self._buffer = self._buffer[:CHUNK_SAMPLES], self._buffer[CHUNK_SAMPLES:]
            self.last_score = float(self._model.predict(chunk)[self._name])
            detected = detected or self.last_score >= self._threshold
        return detected

    def reset(self) -> None:
        self._model.reset()
        self._buffer = np.zeros(0, dtype=np.int16)
        self.last_score = 0.0


def download(models_dir: Path, model: str = "hey_jarvis") -> None:
    """Fetch the pretrained model and its feature extractors once (used by install.ps1)."""
    from openwakeword.utils import download_models

    models_dir.mkdir(parents=True, exist_ok=True)
    download_models(model_names=[model], target_directory=str(models_dir))
