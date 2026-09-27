"""Local HUD server: FastAPI + WebSocket, bound to 127.0.0.1 only.

A random token (new at every launch) is required to open the WebSocket and the
Origin header must be FRIDAY's own page, so no web page opened in a browser can
drive FRIDAY through localhost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from friday.adapters.instance import CONTROL_HEADER, SHOW_PATH
from friday.core.assistant import State
from friday.core.intents import Command
from friday.ui.protocol import client_action

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
_HISTORY = 400  # messages replayed to a window that (re)connects


class AssistantPort(Protocol):
    @property
    def state(self) -> State: ...

    def wake(self, source: str = ...) -> None: ...

    def stop(self) -> None: ...

    def submit_text(self, text: str) -> None: ...

    def execute(self, command: Command) -> None: ...


class Hub:
    """Fan-out of FRIDAY's messages to every open HUD window (callable from any thread)."""

    def __init__(self, history: Iterable[dict[str, Any]] = ()) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._history: deque[dict[str, Any]] = deque(history, maxlen=_HISTORY)

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, message: dict[str, Any]) -> None:
        if message.get("type") not in ("snapshot", "state"):
            self._history.append(message)
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(message)))

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    async def add(self, websocket: WebSocket) -> None:
        self._clients.add(websocket)

    def remove(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def _broadcast(self, message: dict[str, Any]) -> None:
        for websocket in list(self._clients):
            try:
                await websocket.send_json(message)
            except Exception:
                self.remove(websocket)


def create_app(
    assistant: AssistantPort,
    snapshot: Callable[[], dict[str, Any]],
    hub: Hub,
    *,
    token: str,
    port: int,
    models: set[str],
    control: str | None = None,
    on_show: Callable[[], None] | None = None,
) -> FastAPI:
    """`on_show` is called when a second FRIDAY launch presents the `control` secret."""
    allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        hub.attach(asyncio.get_running_loop())
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})

    @app.post(SHOW_PATH)
    async def show(request: Request) -> Response:
        given = request.headers.get(CONTROL_HEADER, "")
        if on_show is None or not control or not secrets.compare_digest(given, control):
            return Response(status_code=403)
        await asyncio.to_thread(on_show)
        return Response(status_code=204)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if websocket.query_params.get("t") != token or (origin and origin not in allowed_origins):
            logger.warning("HUD connection refused (origin %s)", origin)
            await websocket.close(code=4403)
            return
        await websocket.accept()
        await hub.add(websocket)
        try:
            await websocket.send_json(snapshot())
            for message in hub.history:
                await websocket.send_json(message)
            await websocket.send_json({"type": "state", "state": assistant.state.value})
            while True:
                action = client_action(await websocket.receive_json(), models)
                if action is None:
                    continue
                kind, value = action
                if kind == "text":
                    assistant.submit_text(value)
                elif kind == "wake":
                    assistant.wake("interface")
                elif kind == "stop":
                    assistant.stop()
                else:
                    assistant.execute(value)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            hub.remove(websocket)

    return app
