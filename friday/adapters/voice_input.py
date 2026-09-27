"""FRIDAY's ears: a short chime, one recorded utterance, its transcription."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

import numpy as np

from friday.core.ports import AudioClip, AudioOutput, Heard, SpeechToText
from friday.core.transcript import clean_transcript

logger = logging.getLogger(__name__)

CUE_RATE = 22050


class Recorder(Protocol):
    def record(self, cancelled: Callable[[], bool] = ...) -> AudioClip | None: ...


def tone(
    frequencies: tuple[float, ...], note_seconds: float = 0.07, volume: float = 0.2
) -> AudioClip:
    """A soft chime (one short note per frequency, with fades to avoid clicks)."""
    samples_per_note = int(CUE_RATE * note_seconds)
    t = np.arange(samples_per_note) / CUE_RATE
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)
    notes = [np.sin(2 * np.pi * f * t) * fade for f in frequencies]
    wave = np.concatenate(notes) * volume * 32767
    return AudioClip(wave.astype(np.int16).tobytes(), CUE_RATE)


LISTEN_START = tone((660.0, 880.0))
LISTEN_END = tone((880.0, 660.0))


class VoiceInput:
    def __init__(
        self,
        recorder: Recorder,
        stt: SpeechToText,
        cue_output: AudioOutput | None = None,
    ) -> None:
        self._recorder = recorder
        self._stt = stt
        self._cues = cue_output

    def listen(self) -> Heard:
        self._cue(LISTEN_START)
        clip = self._recorder.record()
        self._cue(LISTEN_END)
        if clip is None:
            return Heard(None, "silence")
        raw = self._stt.transcribe(clip)
        text = clean_transcript(raw)
        logger.info("Heard %.1f s: %r -> %r", clip.duration, raw, text)
        return Heard(text, "" if text else "incompris")

    def _cue(self, clip: AudioClip) -> None:
        if self._cues is not None:
            try:
                self._cues.play(clip, lambda: False)
            except Exception:
                logger.exception("Could not play the listening chime")
