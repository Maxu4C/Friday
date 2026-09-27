"""`friday`: FRIDAY with her HUD — native window (pywebview, or the default browser as a
fallback), icon in the notification area, local server bound to 127.0.0.1."""

from __future__ import annotations

import logging
import secrets
import sys
import threading
import time
import webbrowser
from typing import Any

from friday.config import FridayConfig
from friday.core.assistant import AssistantEvent
from friday.core.intents import MuteMic, UnmuteMic
from friday.runtime import Runtime, build_runtime
from friday.ui.protocol import REFRESH, event_message, snapshot
from friday.ui.server import Hub, create_app
from friday.ui.tray import Tray

logger = logging.getLogger(__name__)

WINDOW_SIZE = (1320, 860)


def run_hud(config: FridayConfig, *, window: str = "native") -> int:
    """`window`: "native" (pywebview, browser as fallback), "browser" or "none"."""
    hub = Hub()
    holder: dict[str, Runtime] = {}

    def current_snapshot() -> dict[str, Any]:
        runtime = holder["runtime"]
        return snapshot(runtime.controller, runtime.info, runtime.assistant.state.value)

    def display(event: AssistantEvent) -> None:
        message = event_message(event)
        if message is None:
            return
        if message is not REFRESH:
            hub.publish(message)
        if (message is REFRESH or message["type"] == "turn_done") and "runtime" in holder:
            hub.publish(current_snapshot())

    def report(text: str) -> None:
        logger.warning(text)
        hub.publish({"type": "say", "text": text})

    runtime = build_runtime(config, display, report)
    holder["runtime"] = runtime
    token = secrets.token_urlsafe(24)
    port = config.ui_port
    models = {alias for alias, _ in runtime.controller.model_choices}
    server = _start_server(
        create_app(runtime.assistant, current_snapshot, hub, token=token, port=port, models=models),
        port,
    )
    if server is None:
        print(
            f"Le port {port} est déjà utilisé : FRIDAY est peut-être déjà lancée.", file=sys.stderr
        )
        runtime.close()
        return 1
    url = f"http://127.0.0.1:{port}/?t={token}"
    assistant_thread = threading.Thread(target=runtime.assistant.run, name="friday-assistant")
    assistant_thread.start()

    quit_event = threading.Event()
    window_ref: dict[str, Any] = {}

    def quit_app() -> None:
        quit_event.set()
        runtime.assistant.shutdown()
        window = window_ref.get("window")
        if window is not None:
            window.destroy()

    def toggle_window() -> None:
        window = window_ref.get("window")
        if window is None:
            webbrowser.open(url)
        elif window_ref.get("hidden"):
            window.show()
            window_ref["hidden"] = False
        else:
            window.hide()
            window_ref["hidden"] = True

    def toggle_mute() -> None:
        muted = runtime.controller.mic_muted
        runtime.assistant.execute(UnmuteMic() if muted else MuteMic())

    tray = Tray(
        toggle_window=toggle_window,
        is_muted=lambda: runtime.controller.mic_muted,
        toggle_mute=toggle_mute,
        quit_app=quit_app,
    )
    try:
        tray.start()
    except Exception:
        logger.exception("Tray icon unavailable")

    if window == "none":
        print(f"Interface : {url}", flush=True)
    try:
        native = window == "native" and _open_native_window(url, window_ref, quit_event)
        if not native:
            if window != "none":
                webbrowser.open(url)
            while not quit_event.wait(0.5):  # short waits keep Ctrl+C working
                pass
    except KeyboardInterrupt:
        pass
    finally:
        quit_event.set()
        runtime.assistant.shutdown()
        assistant_thread.join(timeout=10)
        tray.stop()
        runtime.close()
        server.should_exit = True
        runtime.farewell()
    return 0


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


def _open_native_window(url: str, window_ref: dict[str, Any], quit_event: threading.Event) -> bool:
    """Blocks until the app quits. False if no native window could be created."""
    try:
        import webview
    except Exception:
        logger.exception("pywebview unavailable")
        return False
    window = webview.create_window(
        "FRIDAY",
        url,
        width=WINDOW_SIZE[0],
        height=WINDOW_SIZE[1],
        min_size=(900, 600),
        background_color="#04070c",
    )
    if window is None:
        return False
    window_ref["window"] = window

    def on_closing() -> bool:
        if quit_event.is_set():
            return True
        window.hide()  # closing the window keeps FRIDAY running in the notification area
        window_ref["hidden"] = True
        return False

    window.events.closing += on_closing
    try:
        webview.start()
    except Exception:
        logger.exception("Native window failed")
        window_ref.pop("window", None)
        return False
    quit_event.set()
    return True
