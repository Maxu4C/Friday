"""One always-open microphone stream shared by the wake word detector and the recorder.

Sharing a single stream means no word is lost between the wake word and the
request. If the device disappears (headset unplugged), the stream is reopened on
the configured device or, failing that, on the Windows default.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator
from typing import Any

from friday.adapters.audio_io import match_device, query_devices

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512
_STALL_SECONDS = 3.0
_QUEUE_FRAMES = 1000  # ~32 s: a slow consumer drops old frames instead of blocking audio


class Subscription:
    def __init__(self, microphone: Microphone) -> None:
        self._microphone = microphone
        self._frames: queue.Queue[bytes | None] = queue.Queue(maxsize=_QUEUE_FRAMES)

    def deliver(self, frame: bytes) -> None:
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    def get(self, timeout: float) -> bytes | None:
        """Next frame, or None after `timeout` seconds without audio (or once closed)."""
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def __iter__(self) -> Iterator[bytes]:
        while True:
            frame = self._frames.get()
            if frame is None:
                return
            yield frame

    def close(self) -> None:
        self._microphone.unsubscribe(self)
        self._frames.put(None)


class Microphone:
    def __init__(self, device_name: str | None) -> None:
        self._device_name = device_name
        self._subscribers: list[Subscription] = []
        self._lock = threading.Lock()
        self._stream: Any = None
        self._last_frame = 0.0
        self._running = False

    def start(self) -> None:
        self._running = True
        self._open()
        threading.Thread(target=self._watchdog, name="friday-mic-watchdog", daemon=True).start()

    def close(self) -> None:
        self._running = False
        self._close_stream()
        with self._lock:
            subscribers = list(self._subscribers)
        for subscription in subscribers:
            subscription.close()

    def subscribe(self) -> Subscription:
        subscription = Subscription(self)
        with self._lock:
            self._subscribers.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            if subscription in self._subscribers:
                self._subscribers.remove(subscription)

    def deliver(self, frame: bytes) -> None:
        self._last_frame = time.monotonic()
        with self._lock:
            subscribers = list(self._subscribers)
        for subscription in subscribers:
            subscription.deliver(frame)

    # -- stream -------------------------------------------------------------------------

    def _open(self) -> None:
        import sounddevice as sd

        def on_audio(data: Any, _frames: int, _time: Any, status: Any) -> None:
            if status:
                logger.debug("Microphone status: %s", status)
            self.deliver(bytes(data))

        device = match_device(self._device_name, query_devices(), "input")
        for candidate in (device, None) if device is not None else (None,):
            try:
                stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=FRAME_SAMPLES,
                    channels=1,
                    dtype="int16",
                    device=candidate,
                    callback=on_audio,
                )
                stream.start()
            except sd.PortAudioError as exc:
                logger.warning("Cannot open microphone %s: %s", candidate, exc)
                continue
            self._stream = stream
            self._last_frame = time.monotonic()
            logger.info("Microphone open (device %s)", candidate)
            return
        logger.error("No microphone could be opened")

    def _close_stream(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                logger.debug("Error while closing the microphone", exc_info=True)

    def _watchdog(self) -> None:
        while self._running:
            time.sleep(1.0)
            if self._running and time.monotonic() - self._last_frame > _STALL_SECONDS:
                logger.warning("Microphone silent for %.0f s, reopening it", _STALL_SECONDS)
                self._close_stream()
                self._open()
