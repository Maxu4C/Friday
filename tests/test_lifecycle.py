"""Phase 8: single instance, bringing the window back, saved history, importing Claude Code
sessions started in a terminal."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from friday.adapters.claude_transcripts import read, scan
from friday.adapters.instance import CONTROL_HEADER, SHOW_PATH, InstanceFile, InstanceLock
from friday.adapters.json_store import JsonFile
from friday.core.events import Mode
from friday.core.sessions import SessionRegistry
from friday.hud_app import _load_history, run_hud
from friday.ui.protocol import saved_history
from friday.ui.server import Hub, create_app
from tests.test_hud import MODELS, PORT, FakeAssistant

NOW = datetime(2026, 9, 27, 21, 0).astimezone()

# -- single instance ------------------------------------------------------------------------


def test_second_lock_is_refused_until_the_first_is_released(tmp_path: Path) -> None:
    first, second = InstanceLock(tmp_path / "friday.lock"), InstanceLock(tmp_path / "friday.lock")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_lock_is_released_by_the_context_manager(tmp_path: Path) -> None:
    with InstanceLock(tmp_path / "friday.lock") as lock:
        assert lock.acquire()
    with InstanceLock(tmp_path / "friday.lock") as again:
        assert again.acquire()


def test_second_launch_without_a_reachable_friday_exits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config: Any = SimpleNamespace(data_dir=tmp_path, ui_port=PORT)
    with InstanceLock(tmp_path / "friday.lock") as running:
        assert running.acquire()
        assert run_hud(config) == 1  # no runtime is built: the lock is checked first
    assert "déjà lancée" in capsys.readouterr().err


@pytest.fixture
def show_server() -> Iterator[tuple[int, list[str]]]:
    """A stand-in for the running FRIDAY: records the control secret it receives."""
    received: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server API
            received.append(self.headers.get(CONTROL_HEADER, ""))
            ok = self.path == SHOW_PATH and received[-1] == "le-secret"
            self.send_response(204 if ok else 403)
            self.end_headers()

        def log_message(self, *_: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1], received
    server.shutdown()


def test_second_launch_asks_the_running_friday_to_show_herself(
    tmp_path: Path, show_server: tuple[int, list[str]]
) -> None:
    port, received = show_server
    instance = InstanceFile(tmp_path / "instance.json")
    instance.write(port, "le-secret")
    assert instance.ask_to_show()
    assert received == ["le-secret"]


def test_wrong_or_missing_instance_file_means_unreachable(
    tmp_path: Path, show_server: tuple[int, list[str]]
) -> None:
    port, _ = show_server
    instance = InstanceFile(tmp_path / "instance.json")
    assert not instance.ask_to_show()  # no file
    instance.path.write_text("pas du json", encoding="utf-8")
    assert not instance.ask_to_show()
    instance.write(port, "mauvais")
    assert not instance.ask_to_show()
    instance.remove()
    assert not instance.path.exists()


def make_show_client(on_show: Any) -> TestClient:
    app = create_app(
        FakeAssistant(),
        lambda: {"type": "snapshot"},
        Hub(),
        token="secret-token",
        port=PORT,
        models=MODELS,
        control="le-secret",
        on_show=on_show,
    )
    return TestClient(app)


def test_show_endpoint_requires_the_control_secret() -> None:
    calls: list[str] = []
    client = make_show_client(lambda: calls.append("show"))
    assert client.post(SHOW_PATH).status_code == 403
    assert client.post(SHOW_PATH, headers={CONTROL_HEADER: "secret-token"}).status_code == 403
    assert calls == []
    assert client.post(SHOW_PATH, headers={CONTROL_HEADER: "le-secret"}).status_code == 204
    assert calls == ["show"]


def test_show_endpoint_is_closed_without_a_secret() -> None:
    app = create_app(
        FakeAssistant(), lambda: {}, Hub(), token="t", port=PORT, models=MODELS
    )  # fmt: skip
    assert TestClient(app).post(SHOW_PATH, headers={CONTROL_HEADER: ""}).status_code == 403


# -- history kept between launches ------------------------------------------------------------


def test_saved_history_merges_text_and_drops_stale_questions() -> None:
    messages: list[dict[str, Any]] = [
        {"type": "user", "text": "Salut", "spoken": True},
        {"type": "delta", "text": "Bon"},
        {"type": "delta", "text": "soir."},
        {"type": "confirm", "question": "Vous confirmez ?"},
        {"type": "stopped"},
        {"type": "turn_done", "error": None, "denied": []},
        {"type": "delta", "text": "Autre."},
    ]
    assert saved_history(messages) == [
        {"type": "user", "text": "Salut", "spoken": True},
        {"type": "delta", "text": "Bonsoir."},
        {"type": "turn_done", "error": None, "denied": []},
        {"type": "delta", "text": "Autre."},
    ]
    assert messages[1] == {"type": "delta", "text": "Bon"}  # input untouched


def test_history_is_replayed_by_the_hub(tmp_path: Path) -> None:
    store = JsonFile(tmp_path / "history.json")
    store.save({"version": 1, "messages": [{"type": "say", "text": "Bonjour."}, "abîmé", {}]})
    hub = Hub(_load_history(store))
    assert hub.history == [{"type": "say", "text": "Bonjour."}]
    assert _load_history(JsonFile(tmp_path / "absent.json")) == []


# -- importing Claude Code sessions ------------------------------------------------------------


def write_transcript(folder: Path, session_id: str, lines: list[dict[str, Any]]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def user(text: Any, **extra: Any) -> dict[str, Any]:
    return {"type": "user", "sessionId": "s", "cwd": "C:\\projets\\site", "message":
            {"role": "user", "content": text}, **extra}  # fmt: skip


def test_transcript_gives_folder_and_first_real_prompt(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "C--projets-site",
        "abc",
        [
            {"type": "queue-operation", "sessionId": "abc"},
            user("<command-name>/clear</command-name>"),
            user("note interne", isMeta=True),
            user("sous-agent", isSidechain=True),
            user([{"type": "text", "text": "Refais  la page\nd'accueil"}]),
            {"type": "assistant", "cwd": "C:\\ailleurs"},
        ],
    )
    transcript = read(path)
    assert transcript is not None
    assert transcript.session_id == "s"
    assert transcript.cwd == "C:\\projets\\site"
    assert transcript.first_prompt == "Refais la page d'accueil"


def test_scripted_sessions_are_skipped(tmp_path: Path) -> None:
    path = write_transcript(tmp_path / "p", "sdk", [user("Résume ceci", turnOrigin="sdk")])
    assert read(path) is None
    path = write_transcript(tmp_path / "p", "moi", [user("Bonjour", turnOrigin="human")])
    assert read(path) is not None


def test_transcript_without_prompt_is_skipped(tmp_path: Path) -> None:
    path = write_transcript(tmp_path / "p", "vide", [{"type": "queue-operation"}])
    path.write_text(path.read_text(encoding="utf-8") + "{abîmé\n", encoding="utf-8")
    assert read(path) is None


def test_scan_lists_the_most_recent_first_and_is_read_only(tmp_path: Path) -> None:
    old = write_transcript(tmp_path / "a", "vieux", [user("x" * 200, sessionId="vieux")])
    new = write_transcript(tmp_path / "b", "neuf", [user("Bonjour", sessionId="neuf")])
    write_transcript(tmp_path / "b" / "neuf" / "subagents", "agent", [user("non")])
    os.utime(old, (1_700_000_000, 1_700_000_000))
    before = {p: p.read_bytes() for p in (old, new)}

    found = scan(tmp_path)

    assert [t.session_id for t in found] == ["neuf", "vieux"]
    assert found[1].first_prompt.endswith("…") and len(found[1].first_prompt) == 90
    assert scan(tmp_path, limit=1)[0].session_id == "neuf"
    assert {p: p.read_bytes() for p in (old, new)} == before
    assert scan(tmp_path / "absent") == []
    assert scan(tmp_path, skipped=(Path("C:\\PROJETS"),)) == []  # user("…") is in C:\projets


def test_import_adds_a_code_session_without_switching_to_it() -> None:
    registry = SessionRegistry()
    current = registry.create("Maison", Mode.CLAUDE, "opus", "C:\\ws", NOW)
    imported = registry.import_session(
        "site", "sid-1", "opus", "C:\\projets\\site", NOW - timedelta(days=1), "Refais la page"
    )
    assert registry.current is current
    assert imported.mode is Mode.CLAUDE_CODE
    assert (imported.session_id, imported.workspace) == ("sid-1", "C:\\projets\\site")
    assert imported.summary == "Refais la page"
    assert registry.has_session_id("sid-1")
    assert registry.import_session("autre", "sid-1", "opus", "C:\\x", NOW) is imported


def test_import_numbers_a_taken_name() -> None:
    registry = SessionRegistry()
    registry.create("Site", Mode.CLAUDE, "opus", "C:\\ws", NOW)
    assert registry.import_session("site", "a", "opus", "C:\\x", NOW).name == "site 2"
    assert registry.import_session("site", "b", "opus", "C:\\x", NOW).name == "site 3"
    restored = SessionRegistry.from_dict(registry.to_dict())
    assert restored.has_session_id("b")
