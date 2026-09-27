"""Icon in the Windows notification area: show/hide the HUD, mute the microphone, quit."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def _icon_image() -> Any:
    """A glowing ring drawn at runtime (no image file, no copyrighted asset)."""
    from PIL import Image, ImageDraw

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((4, 4, size - 4, size - 4), outline=(70, 210, 255, 255), width=5)
    draw.ellipse((22, 22, size - 22, size - 22), fill=(170, 235, 255, 255))
    return image


class Tray:
    def __init__(
        self,
        *,
        toggle_window: Callable[[], None],
        is_muted: Callable[[], bool],
        toggle_mute: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        self._toggle_window = toggle_window
        self._is_muted = is_muted
        self._toggle_mute = toggle_mute
        self._quit = quit_app
        self._icon: Any = None

    def start(self) -> None:
        import pystray

        menu = pystray.Menu(
            pystray.MenuItem("Afficher / masquer", lambda: self._toggle_window(), default=True),
            pystray.MenuItem(
                "Couper le micro",
                lambda: self._toggle_mute(),
                checked=lambda _item: self._is_muted(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quitter FRIDAY", lambda: self._quit()),
        )
        self._icon = pystray.Icon("friday", _icon_image(), "FRIDAY", menu)
        self._icon.run_detached()

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                logger.debug("Tray icon already stopped", exc_info=True)
