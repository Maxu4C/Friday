"""ClaudeCodeBrain against a scripted fake `claude` process (no real call, no quota)."""

from __future__ import annotations

import json
import queue
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from friday.adapters import brain_claude_code
from friday.adapters.brain_claude_code import (
    FORBIDDEN_FLAGS,
    BrainSettings,
    ClaudeCodeBrain,
    build_command,
    build_env,
)
from friday.core.events import BrainErrorKind, Mode, SessionStarted, TextDelta, TurnCompleted
from friday.core.ports import BrainBusyError, SessionState

Script = Callable[[dict[str, Any]], list[dict[str, Any]] | None]


def init(session_id: str = "sid-1", model: str = "opus") -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "init",
        "session_id": session_id,
        "model": model,
        "tools": [],
        "permissionMode": "default",
    }


def delta(text: str) -> dict[str, Any]:
    return {
        "type": "stream_event",
        "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    }


def result(text: str, session_id: str = "sid-1", **extra: Any) -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": text,
        "session_id": session_id,
        "modelUsage": {},
        **extra,
    }


def aborted(session_id: str = "sid-1") -> dict[str, Any]:
    return {
        "type": "result",
        "subtype": "error_during_execution",
        "is_error": True,
        "terminal_reason": "aborted_streaming",
        "session_id": session_id,
    }


def echo(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    if payload["type"] != "user":
        return []
    content = payload["message"]["content"]
    if content.startswith("/model "):
        synthetic = {"model": "<synthetic>", "content": [{"type": "text", "text": "Set model"}]}
        return [init(), {"type": "assistant", "message": synthetic}, result("Set model")]
    return [init(), delta("Écho : "), delta(content), result(f"Écho : {content}")]


class FakeStdout:
    def __init__(self) -> None:
        self.lines: queue.Queue[str | None] = queue.Queue()

    def __iter__(self) -> Iterator[str]:
        while (line := self.lines.get()) is not None:
            yield line


class FakeStdin:
    def __init__(self, process: FakeProcess) -> None:
        self.process = process
        self.closed = False

    def write(self, data: str) -> int:
        payload = json.loads(data)
        self.process.received.append(payload)
        replies = self.process.script(payload)
        if replies is None:  # simulate a crash
            self.process.exit()
        else:
            for reply in replies:
                self.process.stdout.lines.put(json.dumps(reply, ensure_ascii=False))
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True
        self.process.exit()


class FakeProcess:
    def __init__(self, command: list[str], env: dict[str, str], script: Script) -> None:
        self.command = command
        self.env = env
        self.script = script
        self.received: list[dict[str, Any]] = []
        self.stdout = FakeStdout()
        self.stdin = FakeStdin(self)
        self.stderr = None
        self.returncode: int | None = None
        self.killed = False

    def exit(self) -> None:
        if self.returncode is None:
            self.returncode = 0
            self.stdout.lines.put(None)

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.exit()

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brain_claude_code, "_POLL_SECONDS", 0.01)


def make_settings(tmp_path: Path, timeout: float = 180.0) -> BrainSettings:
    return BrainSettings(
        binary="claude",
        workspace=tmp_path / "workspace",
        runtime_dir=tmp_path / "runtime",
        persona="Tu es FRIDAY.",
        user_names=("Mr",),
        code_tools=("Read", "Edit", "Bash"),
        allowed_tools=("Read", "Bash(git status *)"),
        confirm_tools=("PowerShell(Remove-Item *)",),
        request_timeout=timeout,
    )


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        script: Script = echo,
        *,
        mode: Mode = Mode.CLAUDE,
        model: str = "opus",
        timeout: float = 180.0,
        network: bool = True,
        binary: str | None = "C:/bin/claude.exe",
    ) -> None:
        self.script = script
        self.processes: list[FakeProcess] = []
        self.clock = Clock()
        self.network = network
        self.brain = ClaudeCodeBrain(
            make_settings(tmp_path, timeout),
            SessionState(mode=mode, model=model, name="Session 1"),
            process_factory=self._factory,
            clock=self.clock,
            network_check=lambda: self.network,
            which=lambda _: binary,
        )

    def _factory(self, command: list[str], env: dict[str, str], cwd: Path) -> FakeProcess:
        process = FakeProcess(command, env, self.script)
        self.processes.append(process)
        return process

    def ask(self, text: str) -> tuple[str, TurnCompleted]:
        self.brain.send(text)
        events = list(self.brain.events())
        completed = events[-1]
        assert isinstance(completed, TurnCompleted)
        return "".join(e.text for e in events if isinstance(e, TextDelta)), completed


# -- command line -------------------------------------------------------------


def test_claude_mode_command_disables_every_tool(tmp_path: Path) -> None:
    state = SessionState(Mode.CLAUDE, "haiku", "S")
    command = build_command("claude", state, tmp_path / "p.md", make_settings(tmp_path))
    assert command[command.index("--tools") + 1] == ""
    assert "--permission-mode" not in command
    for flag in ("--safe-mode", "--strict-mcp-config", "--verbose", "--include-partial-messages"):
        assert flag in command
    assert command[command.index("--model") + 1] == "haiku"
    assert command[command.index("--system-prompt-snapshot") + 1] == "off"
    assert "--resume" not in command
    assert not FORBIDDEN_FLAGS.intersection(command)


def test_code_mode_command_restricts_tools_and_permissions(tmp_path: Path) -> None:
    state = SessionState(Mode.CLAUDE_CODE, "opus", "S", session_id="abc")
    command = build_command("claude", state, tmp_path / "p.md", make_settings(tmp_path))
    assert command[command.index("--tools") + 1] == "Read,Edit,Bash"
    assert command[command.index("--permission-mode") + 1] == "acceptEdits"
    assert command[command.index("--permission-prompts") + 1] == "none"
    assert command[command.index("--allowedTools") + 1] == "Read,Bash(git status *)"
    assert command[command.index("--resume") + 1] == "abc"
    assert not FORBIDDEN_FLAGS.intersection(command)


def test_code_mode_forces_confirmation_rules(tmp_path: Path) -> None:
    harness = Harness(tmp_path, mode=Mode.CLAUDE_CODE)
    harness.ask("Supprime tout")
    command = harness.processes[0].command
    settings_file = Path(command[command.index("--settings") + 1])
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    assert settings == {"permissions": {"ask": ["PowerShell(Remove-Item *)"]}}


def test_claude_mode_needs_no_permission_settings(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.ask("Bonjour")
    assert "--settings" not in harness.processes[0].command


def test_env_never_carries_api_keys() -> None:
    env = build_env(
        {"ANTHROPIC_API_KEY": "x", "anthropic_auth_token": "y", "PATH": "C:/bin", "HOME": "h"}
    )
    assert env == {"PATH": "C:/bin", "HOME": "h", "PYTHONIOENCODING": "utf-8"}


# -- conversation ---------------------------------------------------------------


def test_multi_turn_reuses_one_process(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    text, completed = harness.ask("Bonjour")
    assert text == "Écho : Bonjour" and completed.error is None
    harness.ask("Encore")
    assert len(harness.processes) == 1
    assert harness.brain.state.session_id == "sid-1"
    prompt = (tmp_path / "runtime" / "system-prompt.md").read_text(encoding="utf-8")
    assert "Tu es FRIDAY." in prompt and "Mode actuel : conversation" in prompt


def test_session_started_is_forwarded(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.brain.send("Salut")
    events = list(harness.brain.events())
    assert isinstance(events[0], SessionStarted)


def test_only_one_request_at_a_time(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.brain.send("Un")
    with pytest.raises(BrainBusyError):
        harness.brain.send("Deux")


def test_live_model_switch_uses_slash_command(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.ask("Bonjour")
    harness.brain.set_model("haiku")
    assert harness.brain.state.model == "haiku"
    assert len(harness.processes) == 1
    assert harness.processes[0].received[-1]["message"]["content"] == "/model haiku"


def test_model_switch_before_first_request_is_applied_at_launch(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.brain.set_model("fable")
    harness.ask("Bonjour")
    command = harness.processes[0].command
    assert command[command.index("--model") + 1] == "fable"


def test_refused_model_falls_back_to_previous_one(tmp_path: Path) -> None:
    def refuse_fable(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        return [
            init(),
            result("There's an issue with the selected model (fable).", is_error=True,
                   api_error_status=404),
        ]  # fmt: skip

    harness = Harness(tmp_path, refuse_fable)
    harness.brain.set_model("fable")
    _, completed = harness.ask("Bonjour")
    assert completed.error is not None
    assert completed.error.kind is BrainErrorKind.MODEL_NOT_FOUND
    assert harness.brain.state.model == "opus"
    assert harness.brain.state.session_id is None


def test_mode_switch_relaunches_with_resume(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.ask("Bonjour")
    harness.brain.set_mode(Mode.CLAUDE_CODE)
    harness.ask("Liste les fichiers")
    assert len(harness.processes) == 2
    assert harness.processes[0].stdin.closed
    command = harness.processes[1].command
    assert command[command.index("--resume") + 1] == "sid-1"
    assert command[command.index("--tools") + 1] == "Read,Edit,Bash"


def test_new_and_resumed_sessions(tmp_path: Path) -> None:
    harness = Harness(tmp_path)
    harness.ask("Bonjour")
    harness.brain.new_session("Boucherie", Mode.CLAUDE, "opus")
    assert harness.brain.state.session_id is None and harness.brain.state.name == "Boucherie"
    harness.ask("Salut")
    assert "--resume" not in harness.processes[1].command
    harness.brain.resume_session("old-id", "Ancienne", Mode.CLAUDE, "opus")
    harness.ask("Re")
    command = harness.processes[2].command
    assert command[command.index("--resume") + 1] == "old-id"


# -- interruptions and failures -------------------------------------------------


def slow(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Answer nothing until interrupted."""
    if payload["type"] == "control_request":
        return [aborted()]
    return [init(), delta("Un, deux, ")]


def test_interrupt(tmp_path: Path) -> None:
    harness = Harness(tmp_path, slow)
    harness.brain.send("Compte jusqu'à mille")
    events = harness.brain.events()
    assert isinstance(next(events), SessionStarted)
    assert isinstance(next(events), TextDelta)
    harness.brain.interrupt()
    completed = list(events)[-1]
    assert isinstance(completed, TurnCompleted)
    assert completed.error is not None and completed.error.kind is BrainErrorKind.INTERRUPTED
    sent = harness.processes[0].received[-1]
    assert sent["type"] == "control_request" and sent["request"]["subtype"] == "interrupt"


def test_ignored_interrupt_kills_the_process(tmp_path: Path) -> None:
    def deaf(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        return [] if payload["type"] == "control_request" else [init()]

    harness = Harness(tmp_path, deaf)
    harness.brain.send("Bonjour")
    harness.brain.interrupt()
    harness.clock.now += brain_claude_code.INTERRUPT_GRACE_SECONDS + 1
    completed = list(harness.brain.events())[-1]
    assert isinstance(completed, TurnCompleted)
    assert completed.error is not None and completed.error.kind is BrainErrorKind.INTERRUPTED
    assert harness.processes[0].stdin.closed or harness.processes[0].killed


def test_timeout_interrupts_the_request(tmp_path: Path) -> None:
    harness = Harness(tmp_path, slow, timeout=10)
    harness.brain.send("Question sans fin")
    harness.clock.now = 11
    completed = list(harness.brain.events())[-1]
    assert isinstance(completed, TurnCompleted)
    assert completed.error is not None and completed.error.kind is BrainErrorKind.TIMEOUT


def test_rate_limit_retry_is_stopped_not_looped(tmp_path: Path) -> None:
    def limited(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        if payload["type"] == "control_request":
            return [aborted()]
        return [
            init(),
            {"type": "rate_limit_event",
             "rate_limit_info": {"status": "rejected", "resetsAt": 1790542800}},
            {"type": "system", "subtype": "api_retry", "attempt": 1, "error": "rate_limit",
             "error_status": 429},
        ]  # fmt: skip

    harness = Harness(tmp_path, limited)
    _, completed = harness.ask("Bonjour")
    assert completed.error is not None and completed.error.kind is BrainErrorKind.RATE_LIMIT
    assert completed.error.resets_at is not None and completed.error.resets_at.year == 2026
    assert harness.processes[0].received[-1]["type"] == "control_request"


def test_network_down_is_reported_without_launching_claude(tmp_path: Path) -> None:
    harness = Harness(tmp_path, network=False)
    _, completed = harness.ask("Bonjour")
    assert completed.error is not None and completed.error.kind is BrainErrorKind.NETWORK
    assert harness.processes == []


def test_crashed_process_is_restarted_with_resume(tmp_path: Path) -> None:
    calls = {"count": 0}

    def crash_once(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
        calls["count"] += 1
        return None if calls["count"] == 2 else echo(payload)

    harness = Harness(tmp_path, crash_once)
    harness.ask("Bonjour")
    _, completed = harness.ask("Tu vas planter")
    assert completed.error is not None and completed.error.kind is BrainErrorKind.PROCESS_DIED
    text, completed = harness.ask("Toujours là ?")
    assert completed.error is None and text == "Écho : Toujours là ?"
    command = harness.processes[1].command
    assert command[command.index("--resume") + 1] == "sid-1"


def test_missing_binary(tmp_path: Path) -> None:
    harness = Harness(tmp_path, binary=None)
    _, completed = harness.ask("Bonjour")
    assert completed.error is not None and completed.error.kind is BrainErrorKind.PROCESS_DIED
    assert "introuvable" in completed.error.message
