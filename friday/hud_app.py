"""`friday`: FRIDAY with her HUD — native window (pywebview, or the default browser as a
fallback), icon in the notification area, local server bound to 127.0.0.1.

The window opens at once on a "Chargement…" page while the voice, Whisper and the wake
word load (several seconds), then switches to the HUD. Only one FRIDAY runs at a time:
a second launch brings the running window to the front and exits.
"""

from __future__ import annotations

import logging
import secrets
import sys
import threading
import time
import webbrowser
from typing import Any

from friday.adapters.instance import InstanceFile, InstanceLock
from friday.adapters.json_store import JsonFile
from friday.config import FridayConfig
from friday.core.assistant import AssistantEvent
from friday.core.intents import MuteMic, UnmuteMic
from friday.runtime import Runtime, build_runtime
from friday.ui.protocol import REFRESH, event_message, saved_history, snapshot
from friday.ui.server import Hub, create_app
from friday.ui.tray import Tray

logger = logging.getLogger(__name__)

WINDOW_SIZE = (1320, 860)
HISTORY_VERSION = 1
_PAGE = (
    '<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>'
    "body{{margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;background:#04070c;color:#7fd8ff;font:15px 'Segoe UI',sans-serif;"
    "letter-spacing:.25em}}p{{color:#5b7185;letter-spacing:normal;max-width:34em;"
    "text-align:center}}</style></head><body><div>{title}</div><p>{detail}</p></body></html>"
)
LOADING_PAGE = _PAGE.format(
    title="FRIDAY — CHARGEMENT…", detail="Voix, reconnaissance vocale et mot d'activation."
)


def run_hud(config: FridayConfig, *, window: str = "native") -> int:
    """`window`: "native" (pywebview, browser as fallback), "browser" or "none"."""
    lock = InstanceLock(config.data_dir / "friday.lock")
    if not lock.acquire():
        if InstanceFile(config.data_dir / "instance.json").ask_to_show():
            logger.info("FRIDAY already running: her window was brought to the front")
            return 0
        print("FRIDAY est déjà lancée (ou en cours de chargement).", file=sys.stderr)
        return 1
    try:
        return HudApp(config, window).run()
    finally:
        lock.release()


class HudApp:
    def __init__(self, config: FridayConfig, window: str) -> None:
        self._config = config
        self._mode = window
        self._history_file = JsonFile(config.data_dir / "history.json")
        self._instance = InstanceFile(config.data_dir / "instance.json")
        self.hub = Hub(_load_history(self._history_file))
        self._quit = threading.Event()
        self._boot_lock = threading.Lock()
        self._booted: bool | None = None  # None: not tried yet
        self._runtime: Runtime | None = None
        self._server: Any = None
        self._assistant_thread: threading.Thread | None = None
        self._tray: Tray | None = None
        self._url = ""
        self._window: Any = None
        self._hidden = False

    # -- lifecycle ---------------------------------------------------------------------

    def run(self) -> int:
        try:
            if self._mode == "native" and self._run_native():
                return 0 if self._booted else 1
            print("FRIDAY — chargement…", flush=True)
            if not self._boot():
                return 1
            if self._mode == "none":
                print(f"Interface : {self._url}", flush=True)
            else:
                webbrowser.open(self._url)
            while not self._quit.wait(0.5):  # short waits keep Ctrl+C working
                pass
            return 0
        except KeyboardInterrupt:
            return 0
        finally:
            self._cleanup()

    def _run_native(self) -> bool:
        """Blocks until the app quits. False if no native window could be created."""
        try:
            import webview
        except Exception:
            logger.exception("pywebview unavailable")
            return False
        window = webview.create_window(
            "FRIDAY",
            html=LOADING_PAGE,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=(900, 600),
            background_color="#04070c",
        )
        if window is None:
            return False
        self._window = window
        window.events.closing += self._on_closing
        try:
            webview.start(self._boot_in_window)  # the function runs in its own thread
        except Exception:
            logger.exception("Native window failed")
            self._window = None
            return False
        self._quit.set()
        return True

    def _boot_in_window(self) -> None:
        booted = self._boot()
        window = self._window
        if window is None or self._quit.is_set():
            return
        try:
            if booted:
                window.load_url(self._url)
            else:
                window.load_html(
                    _PAGE.format(
                        title="FRIDAY N'A PAS PU DÉMARRER",
                        detail=f"Le port {self._config.ui_port} est déjà utilisé par un autre "
                        "programme (ui.port dans config\\friday.yaml). Fermez cette fenêtre.",
                    )
                )
        except Exception:
            logger.exception("Cannot show the HUD in the window")

    def _on_closing(self) -> bool:
        if self._quit.is_set() or not self._booted:
            self._quit.set()
            return True
        self._window.hide()  # closing the window keeps FRIDAY running in the notification area
        self._hidden = True
        return False

    def _boot(self) -> bool:
        with self._boot_lock:
            if self._booted is None:
                self._booted = self._start()
            return self._booted

    def _start(self) -> bool:
        runtime = build_runtime(self._config, self._display, self._report)
        self._runtime = runtime
        port = self._config.ui_port
        control = secrets.token_urlsafe(24)
        token = secrets.token_urlsafe(24)
        app = create_app(
            runtime.assistant,
            self._snapshot,
            self.hub,
            token=token,
            port=port,
            models={alias for alias, _ in runtime.controller.model_choices},
            control=control,
            on_show=self.show_window,
        )
        self._server = _start_server(app, port)
        if self._server is None:
            logger.error("Port %s already in use", port)
            print(f"Le port {port} est déjà utilisé par un autre programme.", file=sys.stderr)
            return False
        self._instance.write(port, control)
        self._url = f"http://127.0.0.1:{port}/?t={token}"
        self._assistant_thread = threading.Thread(
            target=runtime.assistant.run, name="friday-assistant"
        )
        self._assistant_thread.start()
        self._tray = Tray(
            toggle_window=self.toggle_window,
            is_muted=lambda: runtime.controller.mic_muted,
            toggle_mute=self._toggle_mute,
            quit_app=self.quit,
        )
        try:
            self._tray.start()
        except Exception:
            logger.exception("Tray icon unavailable")
        return True

    def _cleanup(self) -> None:
        """Stop Claude, save sessions and history, release the microphone."""
        self._quit.set()
        with self._boot_lock:  # a launch still loading finishes first
            runtime = self._runtime
        if runtime is None:
            return
        runtime.assistant.shutdown()  # closes the claude process and saves the sessions
        if self._assistant_thread is not None:
            self._assistant_thread.join(timeout=10)
        if self._tray is not None:
            self._tray.stop()
        runtime.close()
        if self._server is not None:
            self._server.should_exit = True
        if self._booted:
            self._instance.remove()
            self._save_history()
            runtime.farewell()
        elif runtime.narrator is not None:
            runtime.narrator.close()

    # -- actions from the tray and from a second launch ---------------------------------

    def quit(self) -> None:
        self._quit.set()
        if self._runtime is not None:
            self._runtime.assistant.shutdown()
        if self._window is not None:
            self._window.destroy()

    def show_window(self) -> None:
        window = self._window
        if window is None:
            if self._url:
                webbrowser.open(self._url)
            return
        try:
            window.show()
            window.restore()
            window.on_top = True  # Windows only brings a window forward this way
            window.on_top = False
        except Exception:
            logger.exception("Cannot show the window")
        self._hidden = False

    def toggle_window(self) -> None:
        if self._window is None or self._hidden:
            self.show_window()
        else:
            self._window.hide()
            self._hidden = True

    def _toggle_mute(self) -> None:
        if self._runtime is not None:
            muted = self._runtime.controller.mic_muted
            self._runtime.assistant.execute(UnmuteMic() if muted else MuteMic())

    # -- messages to the HUD -------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        runtime = self._runtime
        assert runtime is not None
        return snapshot(runtime.controller, runtime.info, runtime.assistant.state.value)

    def _display(self, event: AssistantEvent) -> None:
        message = event_message(event)
        if message is None:
            return
        if message is not REFRESH:
            self.hub.publish(message)
        if (message is REFRESH or message["type"] == "turn_done") and self._booted:
            self.hub.publish(self._snapshot())
        if message is not REFRESH and message["type"] == "turn_done":
            self._save_history()  # survives a PC shutdown without quitting FRIDAY

    def _report(self, text: str) -> None:
        logger.warning(text)
        self.hub.publish({"type": "say", "text": text})

    def _save_history(self) -> None:
        try:
            self._history_file.save(
                {"version": HISTORY_VERSION, "messages": saved_history(self.hub.history)}
            )
        except OSError:
            logger.exception("Cannot save the HUD history")


def _load_history(store: JsonFile) -> list[dict[str, Any]]:
    data = store.load() or {}
    messages = data.get("messages")
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict) and isinstance(m.get("type"), str)]


def _start_server(app: Any, port: int) -> Any:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="friday-hud-server", daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    return server if server.started else None
