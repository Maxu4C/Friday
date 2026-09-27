"""Audio device discovery and name-based selection.

Device indices shift whenever a headset is plugged or unplugged, so the
configuration stores device *names* and they are resolved to an index at
runtime. An unknown or unplugged device falls back to the system default.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from friday.core.ports import AudioClip

logger = logging.getLogger(__name__)

Kind = Literal["input", "output"]

# DirectSound exposes full names and resamples to 16 kHz on its own; MME also
# resamples but truncates names to 31 characters; WASAPI needs the native rate.
HOSTAPI_PREFERENCE = ("Windows DirectSound", "MME", "Windows WASAPI")

# Virtual aliases of "the default device", not physical devices.
_ALIASES = ("mappeur de sons", "pilote de capture audio principal", "peripherique audio principal")


@dataclass(frozen=True)
class AudioDevice:
    index: int
    name: str
    hostapi: str
    max_input_channels: int
    max_output_channels: int

    def supports(self, kind: Kind) -> bool:
        channels = self.max_input_channels if kind == "input" else self.max_output_channels
        return channels > 0


def normalize(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(stripped.casefold().split())


def _is_alias(device: AudioDevice) -> bool:
    return normalize(device.name).startswith(_ALIASES)


def _hostapi_rank(device: AudioDevice) -> int:
    try:
        return HOSTAPI_PREFERENCE.index(device.hostapi)
    except ValueError:
        return len(HOSTAPI_PREFERENCE)


def _matches(wanted: str, device_name: str) -> bool:
    """Exact or partial match; MME names are truncated so a prefix counts too."""
    candidate = normalize(device_name)
    return wanted == candidate or wanted in candidate or wanted.startswith(candidate)


def match_device(name: str | None, devices: Sequence[AudioDevice], kind: Kind) -> int | None:
    """Return the index of the device called `name`, or None for the system default."""
    if not name or not name.strip():
        return None
    wanted = normalize(name)
    candidates = [d for d in devices if d.supports(kind) and not _is_alias(d)]
    exact = [d for d in candidates if normalize(d.name) == wanted]
    pool = exact or [d for d in candidates if _matches(wanted, d.name)]
    if not pool:
        logger.warning("Audio %s device %r not found, using system default", kind, name)
        return None
    return min(pool, key=lambda d: (_hostapi_rank(d), d.index)).index


def device_names(devices: Sequence[AudioDevice], kind: Kind) -> list[str]:
    """Unique physical device names for `kind`, full (untruncated) spelling first."""
    usable = sorted(
        (d for d in devices if d.supports(kind) and not _is_alias(d) and _hostapi_rank(d) < 3),
        key=lambda d: -len(d.name),
    )
    names: list[str] = []
    for device in usable:
        key = normalize(device.name)
        if not any(normalize(known).startswith(key) for known in names):
            names.append(device.name)
    return sorted(names, key=normalize)


def query_devices() -> list[AudioDevice]:
    import sounddevice as sd

    hostapis = [api["name"] for api in sd.query_hostapis()]
    return [
        AudioDevice(
            index=index,
            name=info["name"],
            hostapi=hostapis[info["hostapi"]],
            max_input_channels=info["max_input_channels"],
            max_output_channels=info["max_output_channels"],
        )
        for index, info in enumerate(sd.query_devices())
    ]


class SoundDevicePlayer:
    """Plays clips on the configured output, resolved by name before each clip.

    A headset unplugged between two sentences simply moves playback to the
    Windows default output instead of crashing.
    """

    BLOCK_SECONDS = 0.05

    def __init__(self, device_name: str | None = None) -> None:
        self._device_name = device_name

    def play(self, clip: AudioClip, cancelled: Callable[[], bool]) -> None:
        import numpy as np
        import sounddevice as sd

        samples = np.frombuffer(clip.pcm, dtype=np.int16).reshape(-1, clip.channels)
        device = match_device(self._device_name, query_devices(), "output")
        try:
            self._write(sd, samples, clip, device, cancelled)
        except sd.PortAudioError:
            if device is None:
                raise
            logger.warning("Output device %r failed, using the default one", self._device_name)
            self._write(sd, samples, clip, None, cancelled)

    def _write(
        self,
        sd: Any,
        samples: Any,
        clip: AudioClip,
        device: int | None,
        cancelled: Callable[[], bool],
    ) -> None:
        block = max(1, int(clip.sample_rate * self.BLOCK_SECONDS))
        with sd.OutputStream(
            samplerate=clip.sample_rate, channels=clip.channels, dtype="int16", device=device
        ) as stream:
            for start in range(0, len(samples), block):
                if cancelled():
                    stream.abort()
                    return
                stream.write(samples[start : start + block])


def default_device_name(devices: Sequence[AudioDevice], kind: Kind) -> str | None:
    import sounddevice as sd

    default_in, default_out = sd.default.device
    index = default_in if kind == "input" else default_out
    name = next((d.name for d in devices if d.index == index), None)
    if name is None:
        return None
    # The default index often points at a truncated MME name; return the full one.
    wanted = normalize(name)
    return next((n for n in device_names(devices, kind) if normalize(n).startswith(wanted)), name)
