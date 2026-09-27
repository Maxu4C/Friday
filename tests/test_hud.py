"""Phase 7: HUD messages, interface commands and the local server's protections."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from friday.core.assistant import ShowBlock, State, StateEvent, UserSaid
from friday.core.controller import Ask, ConfirmAction, Say, StateChanged, StopSpeaking
from friday.core.events import (
    BrainError,
    BrainErrorKind,
    Mode,
    TextDelta,
    ToolResult,
    ToolUse,
    TurnCompleted,
)
from friday.core.intents import (
    AutoModel,
    ForgetSession,
    MuteMic,
    NewSession,
    RenameSession,
    ResumeSession,
    SetMode,
    SetModel,
    UnmuteMic,
)
from friday.ui.protocol import REFRESH, RuntimeInfo, client_action, event_message, snapshot
from friday.ui.server import Hub, create_app
from tests.test_controller import Harness

MODELS = {"haiku", "opus", "fable"}
INFO = RuntimeInfo(voice=True, microphone=True, whisper=True, wake_word="Hey Jarvis",
                   hotkey="Ctrl+Alt+F")  # fmt: skip

# -- messages to the HUD ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("event", "message"),
    [
        (TextDelta("Bon"), {"type": "delta", "text": "Bon"}),
        (ToolUse("t1", "Write", {"file_path": "C:/a.txt", "content": "x"}),
         {"type": "tool", "name": "Write", "detail": "C:/a.txt"}),
        (ToolResult("t1", True, "échec"), {"type": "tool_error", "summary": "échec"}),
        (ToolResult("t1", False, "ok"), None),
        (TurnCompleted("x", "s", error=BrainError(BrainErrorKind.RATE_LIMIT),
                       permission_denials=("Bash",)),
         {"type": "turn_done", "error": "rate_limit", "denied": ["Bash"]}),
        (Say("Bonjour."), {"type": "say", "text": "Bonjour."}),
        (Ask("Laquelle ?"), {"type": "ask", "text": "Laquelle ?"}),
        (ConfirmAction("Vous confirmez ?", "PowerShell : rm x", True, 2),
         {"type": "confirm", "question": "Vous confirmez ?", "detail": "PowerShell : rm x",
          "dangerous": True, "step": 2}),
        (StateEvent(State.LISTENING), {"type": "state", "state": "listening"}),
        (UserSaid("Salut", True), {"type": "user", "text": "Salut", "spoken": True}),
        (ShowBlock("```py\nx\n```"), {"type": "block", "text": "```py\nx\n```"}),
        (StopSpeaking(), {"type": "stopped"}),
        (StateChanged("S", Mode.CLAUDE, "opus", "Opus 5.5", False), REFRESH),
    ],
)  # fmt: skip
def test_event_messages(event: Any, message: dict[str, Any] | None) -> None:
    assert event_message(event) == message


def test_snapshot_describes_the_current_session() -> None:
    harness = Harness()
    harness.run("nouvelle session pour le projet boucherie", "utilise Fable", "Quelle heure ?")
    data = snapshot(harness.controller, INFO, "idle")
    assert data["session"]["name"] == "boucherie"
    assert data["session"]["locked"] == "fable"
    assert data["session"]["model_label"] == "Fable 5.1"
    assert [s["name"] for s in data["sessions"]] == ["boucherie", "Session 1"]
    assert {"alias": "opus", "label": "Opus 5.5"} in data["models"]
    assert data["usage"] == {"Fable 5.1": 1}
    assert data["indicators"]["wake_word"] == "Hey Jarvis"


# -- messages from the HUD -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "action"),
    [
        ({"type": "text", "value": " Bonjour "}, ("text", "Bonjour")),
        ({"type": "ptt"}, ("wake", None)),
        ({"type": "stop"}, ("stop", None)),
        ({"type": "mode", "value": "claude_code"}, ("command", SetMode(Mode.CLAUDE_CODE))),
        ({"type": "model", "value": "fable"}, ("command", SetModel("fable"))),
        ({"type": "model", "value": "auto"}, ("command", AutoModel())),
        ({"type": "session_new", "value": ""}, ("command", NewSession(None))),
        ({"type": "session_new", "value": "Boucherie"}, ("command", NewSession("Boucherie"))),
        ({"type": "session_resume", "value": "Boucherie"}, ("command", ResumeSession("Boucherie"))),
        ({"type": "session_rename", "value": "Resto"}, ("command", RenameSession("Resto"))),
        ({"type": "session_forget", "value": "Resto"}, ("command", ForgetSession("Resto"))),
        ({"type": "mute"}, ("command", MuteMic())),
        ({"type": "unmute"}, ("command", UnmuteMic())),
    ],
)  # fmt: skip
def test_client_actions(message: dict[str, Any], action: tuple[str, Any]) -> None:
    assert client_action(message, MODELS) == action


@pytest.mark.parametrize(
    "message",
    [
        "texte brut",
        {"type": "text", "value": "   "},
        {"type": "model", "value": "gpt-5"},
        {"type": "mode", "value": "turbo"},
        {"type": "session_resume", "value": ""},
        {"type": "shell", "value": "rm -rf /"},
        {"type": "text", "value": 42},
    ],
)
def test_malformed_client_messages_are_ignored(message: Any) -> None:
    assert client_action(message, MODELS) is None


# -- server ---------------------------------------------------------------------------------


class FakeAssistant:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.state = State.IDLE

    def wake(self, source: str = "") -> None:
        self.calls.append(("wake", source))

    def stop(self) -> None:
        self.calls.append(("stop", None))

    def submit_text(self, text: str) -> None:
        self.calls.append(("text", text))

    def execute(self, command: Any) -> None:
        self.calls.append(("command", command))


PORT = 8765
ORIGIN = {"origin": f"http://127.0.0.1:{PORT}"}


def make_client() -> tuple[TestClient, FakeAssistant, Hub]:
    assistant, hub = FakeAssistant(), Hub()
    app = create_app(
        assistant,
        lambda: {"type": "snapshot", "state": "idle"},
        hub,
        token="secret-token",
        port=PORT,
        models=MODELS,
    )
    return TestClient(app), assistant, hub


def test_page_is_served() -> None:
    client, _, _ = make_client()
    with client:
        page = client.get("/")
        assert page.status_code == 200 and "F.R.I.D.A.Y." in page.text
        assert client.get("/static/hud.js").status_code == 200


@pytest.mark.parametrize(
    ("url", "headers"),
    [
        ("/ws", ORIGIN),  # no token
        ("/ws?t=wrong", ORIGIN),  # wrong token
        ("/ws?t=secret-token", {"origin": "https://evil.example"}),  # foreign web page
        ("/ws?t=secret-token", {"origin": "http://127.0.0.1:9999"}),  # other local port
    ],
)
def test_websocket_refuses_strangers(url: str, headers: dict[str, str]) -> None:
    client, assistant, _ = make_client()
    with (
        client,
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(url, headers=headers) as ws,
    ):
        ws.receive_json()
    assert closed.value.code == 4403
    assert assistant.calls == []


def test_websocket_session() -> None:
    client, assistant, hub = make_client()
    with client:
        hub.publish({"type": "say", "text": "Bonjour."})  # history replayed on connect
        with client.websocket_connect("/ws?t=secret-token", headers=ORIGIN) as ws:
            assert ws.receive_json()["type"] == "snapshot"
            assert ws.receive_json() == {"type": "say", "text": "Bonjour."}
            assert ws.receive_json() == {"type": "state", "state": "idle"}
            for message in (
                {"type": "text", "value": "Quelle heure ?"},
                {"type": "ptt"},
                {"type": "model", "value": "haiku"},
                {"type": "shell", "value": "format C:"},
                {"type": "stop"},
            ):
                ws.send_json(message)
            hub.publish({"type": "delta", "text": "Il est midi."})
            assert ws.receive_json() == {"type": "delta", "text": "Il est midi."}
    assert assistant.calls == [
        ("text", "Quelle heure ?"),
        ("wake", "interface"),
        ("command", SetModel("haiku")),
        ("stop", None),
    ]


def test_server_binds_only_to_localhost() -> None:
    import inspect

    from friday import hud_app

    assert 'host="127.0.0.1"' in inspect.getsource(hud_app._start_server)
