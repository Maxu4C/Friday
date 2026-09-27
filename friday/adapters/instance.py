"""One FRIDAY at a time: a lock file held for the whole run, plus a small file telling a
second launch how to bring the running window back to the front."""

from __future__ import annotations

import json
import logging
import msvcrt
import urllib.request
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)

SHOW_PATH = "/api/show"
CONTROL_HEADER = "X-Friday-Control"


class InstanceLock:
    """Byte-range lock on `path`; Windows releases it by itself if FRIDAY crashes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[bytes] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # noqa: SIM115 - kept open while FRIDAY runs
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._file.close()
        self._file = None

    def __enter__(self) -> InstanceLock:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()


class InstanceFile:
    """data/instance.json: port and secret of the running HUD (local file, never shared)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, port: int, control: str) -> None:
        self.path.write_text(json.dumps({"port": port, "control": control}), encoding="utf-8")

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)

    def ask_to_show(self, timeout: float = 3.0) -> bool:
        """Ask the running FRIDAY to show her window. False if she could not be reached."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            port, control = int(data["port"]), str(data["control"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}{SHOW_PATH}",
            method="POST",
            headers={CONTROL_HEADER: control},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return bool(response.status == 204)
        except OSError as exc:
            logger.info("Running FRIDAY unreachable: %s", exc)
            return False
