"""Speak sentences one after another: synthesize the next while the current one plays.

`stop()` silences FRIDAY immediately: the sentence being played is cut and every
queued sentence is dropped.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable

from friday.core.ports import AudioClip, AudioOutput, TextToSpeech
from friday.core.speech import clean_for_speech

logger = logging.getLogger(__name__)


class Narrator:
    def __init__(
        self,
        tts: TextToSpeech,
        output: AudioOutput,
        *,
        on_speaking: Callable[[bool], None] | None = None,
    ) -> None:
        self._tts = tts
        self._output = output
        self._listeners: list[Callable[[bool], None]] = [on_speaking] if on_speaking else []
        # None closes the queue.
        self._texts: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._clips: queue.Queue[tuple[int, AudioClip] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = 0
        self._idle = threading.Event()
        self._idle.set()
        self._threads = [
            threading.Thread(target=self._synthesize_loop, name="friday-tts", daemon=True),
            threading.Thread(target=self._play_loop, name="friday-audio", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    @property
    def speaking(self) -> bool:
        return not self._idle.is_set()

    def add_listener(self, listener: Callable[[bool], None]) -> None:
        """Called with True when FRIDAY starts speaking and False when she falls silent."""
        self._listeners.append(listener)

    def say(self, text: str) -> None:
        spoken = clean_for_speech(text)
        if not spoken:
            return
        with self._lock:
            self._pending += 1
            if self._pending == 1:
                self._idle.clear()
                self._notify(True)
            generation = self._generation
        self._texts.put((generation, spoken))

    def stop(self) -> None:
        """Cut the current sentence and drop the queued ones."""
        with self._lock:
            self._generation += 1

    def wait(self, timeout: float | None = None) -> bool:
        """Block until everything said has been played (or dropped)."""
        return self._idle.wait(timeout)

    def close(self) -> None:
        self.stop()
        self._texts.put(None)
        for thread in self._threads:
            thread.join(timeout=2)

    # -- workers -------------------------------------------------------------------

    def _synthesize_loop(self) -> None:
        while (item := self._texts.get()) is not None:
            generation, text = item
            if generation != self._generation:
                self._done()
                continue
            try:
                clip = self._tts.synthesize(text)
            except Exception:
                logger.exception("Speech synthesis failed for: %s", text[:80])
                self._done()
                continue
            self._clips.put((generation, clip))
        self._clips.put(None)

    def _play_loop(self) -> None:
        while (item := self._clips.get()) is not None:
            generation, clip = item
            if generation == self._generation:
                self._play(generation, clip)
            self._done()

    def _play(self, generation: int, clip: AudioClip) -> None:
        try:
            self._output.play(clip, lambda: generation != self._generation)
        except Exception:
            logger.exception("Audio playback failed")

    def _done(self) -> None:
        with self._lock:
            self._pending -= 1
            if self._pending == 0:
                self._idle.set()
                self._notify(False)

    def _notify(self, speaking: bool) -> None:
        for listener in self._listeners:
            try:
                listener(speaking)
            except Exception:
                logger.exception("Speaking listener failed")
