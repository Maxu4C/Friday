"""Voice activity detection on 512-sample frames at 16 kHz.

SileroVAD runs the Silero v6 ONNX model shipped with faster-whisper, keeping its
recurrent state between frames so it can follow live microphone audio.
EnergyVAD is the dependency-free fallback (loudness above the noise floor).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

FRAME_SAMPLES = 512
_CONTEXT_SAMPLES = 64


def _as_float(frame: bytes) -> np.ndarray:
    return np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0


class SileroVAD:
    def __init__(self, model_path: Path | None = None) -> None:
        import onnxruntime

        if model_path is None:
            from faster_whisper.vad import get_assets_path

            model_path = Path(get_assets_path()) / "silero_vad_v6.onnx"
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        self._session = onnxruntime.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"], sess_options=options
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(_CONTEXT_SAMPLES, dtype=np.float32)

    def probability(self, frame: bytes) -> float:
        samples = _as_float(frame)
        if len(samples) != FRAME_SAMPLES:
            samples = np.resize(samples, FRAME_SAMPLES)
        batch = np.concatenate([self._context, samples])[np.newaxis, :]
        output, self._h, self._c = self._session.run(
            None, {"input": batch, "h": self._h, "c": self._c}
        )
        self._context = samples[-_CONTEXT_SAMPLES:]
        return float(np.asarray(output).reshape(-1)[0])


class EnergyVAD:
    """Speech = loud enough above an adaptive noise floor."""

    def __init__(self, margin_db: float = 12.0) -> None:
        self._margin = margin_db
        self.reset()

    def reset(self) -> None:
        self._floor_db = -60.0

    def probability(self, frame: bytes) -> float:
        samples = _as_float(frame)
        rms = float(np.sqrt(np.mean(samples**2))) if len(samples) else 0.0
        level = 20 * math.log10(max(rms, 1e-6))
        above = level - self._floor_db
        # The floor follows quiet frames quickly and loud ones very slowly.
        rate = 0.05 if above < self._margin else 0.001
        self._floor_db += rate * (level - self._floor_db)
        return min(1.0, max(0.0, (above - self._margin / 2) / self._margin))
