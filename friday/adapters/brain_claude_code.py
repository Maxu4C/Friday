"""FRIDAY's brain: the real `claude` binary (Claude Code) driven over stream-json.

One long-lived `claude -p` process per session receives user messages on stdin
and streams events on stdout. Authentication stays inside that process: FRIDAY
never reads or passes any token, and strips API keys from its environment so
the Claude subscription is always used.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Protocol

from friday.adapters.claude_stream import api_retry_error, parse_event
from friday.core.events import (
    ApiRetry,
    BrainError,
    BrainErrorKind,
    BrainEvent,
    Mode,
    RateLimitStatus,
    SessionStarted,
    ToolUse,
    TurnCompleted,
)
from friday.core.ports import BrainBusyError, SessionState
from friday.core.prompt import build_system_prompt

logger = logging.getLogger(__name__)
actions_log = logging.getLogger("friday.actions")

FORBIDDEN_FLAGS = frozenset(
    {"--bare", "--dangerously-skip-permissions", "--allow-dangerously-skip-permissions"}
)
STRIPPED_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
INTERRUPT_GRACE_SECONDS = 5.0
_POLL_SECONDS = 0.2
_EOF = object()


class BrainUnavailableError(RuntimeError):
    """The claude binary cannot be started."""


class ProcessHandle(Protocol):
    stdin: IO[str] | None
    stdout: IO[str] | None
    stderr: IO[str] | None

    def poll(self) -> int | None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


ProcessFactory = Callable[[list[str], dict[str, str], Path], ProcessHandle]


@dataclass(frozen=True)
class BrainSettings:
    binary: str
    workspace: Path
    runtime_dir: Path
    persona: str
    user_names: tuple[str, ...]
    code_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    confirm_tools: tuple[str, ...] = ()
    request_timeout: float = 180.0


def permission_settings(settings: BrainSettings) -> dict[str, Any]:
    """Settings passed with --settings: `ask` rules win over acceptEdits auto-approval."""
    return {"permissions": {"ask": list(settings.confirm_tools)}}


def build_command(
    binary: str,
    state: SessionState,
    prompt_file: Path,
    settings: BrainSettings,
    settings_file: Path | None = None,
) -> list[str]:
    command = [
        binary,
        "-p",
        "--output-format", "stream-json",
        "--input-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--model", state.model,
        # Ignore the user's plugins, hooks, MCP servers and CLAUDE.md files: FRIDAY
        # sessions only get the persona below and the tools of the active mode.
        "--safe-mode",
        "--strict-mcp-config",
        # Re-render the appended prompt at each launch (mode and date change).
        "--system-prompt-snapshot", "off",
        "--append-system-prompt-file", str(prompt_file),
    ]  # fmt: skip
    if state.mode is Mode.CLAUDE:
        command += ["--tools", ""]
    else:
        command += [
            "--tools", ",".join(settings.code_tools),
            "--permission-mode", "acceptEdits",
            # Until the permission server (phase 6), anything not allowed is refused.
            "--permission-prompts", "none",
        ]  # fmt: skip
        if settings.allowed_tools:
            command += ["--allowedTools", ",".join(settings.allowed_tools)]
        if settings_file is not None:
            command += ["--settings", str(settings_file)]
    if state.session_id:
        command += ["--resume", state.session_id]
    forbidden = FORBIDDEN_FLAGS.intersection(command)
    if forbidden:
        raise AssertionError(f"Forbidden claude flags: {sorted(forbidden)}")
    return command


def build_env(base: Mapping[str, str]) -> dict[str, str]:
    env = {key: value for key, value in base.items() if key.upper() not in STRIPPED_ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def popen_factory(command: list[str], env: dict[str, str], cwd: Path) -> ProcessHandle:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )


def network_available(host: str = "api.anthropic.com", timeout: float = 2.0) -> bool:
    """Fast DNS check so a missing network is reported in seconds, not minutes."""
    resolved = threading.Event()

    def resolve() -> None:
        try:
            socket.getaddrinfo(host, 443)
            resolved.set()
        except OSError:
            pass

    threading.Thread(target=resolve, daemon=True).start()
    return resolved.wait(timeout)


class _Process:
    def __init__(self, handle: ProcessHandle) -> None:
        self.handle = handle
        self.queue: queue.Queue[object] = queue.Queue()
        self._write_lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        if handle.stderr is not None:
            threading.Thread(target=self._read_stderr, args=(handle.stderr,), daemon=True).start()

    @property
    def alive(self) -> bool:
        return self.handle.poll() is None

    def write(self, payload: dict[str, Any]) -> None:
        if self.handle.stdin is None:
            raise OSError("claude stdin is closed")
        with self._write_lock:
            self.handle.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.handle.stdin.flush()

    def stop(self) -> None:
        try:
            if self.handle.stdin is not None:
                self.handle.stdin.close()
            self.handle.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired, ValueError):
            self.handle.kill()
            try:
                self.handle.wait(timeout=3)
            except subprocess.TimeoutExpired:
                logger.warning("claude process did not exit after kill")

    def _read_stdout(self) -> None:
        stdout: Iterable[str] = self.handle.stdout or ()
        for line in stdout:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("claude non-JSON output: %s", line[:200])
                continue
            for event in parse_event(raw):
                self.queue.put(event)
        self.queue.put(_EOF)

    @staticmethod
    def _read_stderr(stream: IO[str]) -> None:
        for line in stream:
            if line.strip():
                logger.debug("claude stderr: %s", line.rstrip()[:500])


@dataclass
class _Turn:
    deadline: float
    session_before: str | None
    model_before: str | None
    interrupt_deadline: float | None = None
    forced_error: BrainError | None = None
    pending: list[BrainEvent] = field(default_factory=list)


class ClaudeCodeBrain:
    def __init__(
        self,
        settings: BrainSettings,
        state: SessionState,
        *,
        process_factory: ProcessFactory = popen_factory,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
        network_check: Callable[[], bool] = network_available,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self._settings = settings
        self._state = state
        self._factory = process_factory
        self._clock = clock
        self._now = now
        self._network_check = network_check
        self._which = which
        self._process: _Process | None = None
        self._turn: _Turn | None = None
        self._unconfirmed_model: str | None = None  # model to restore if the new one is refused
        self._last_rate_limit: RateLimitStatus | None = None

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def last_rate_limit(self) -> RateLimitStatus | None:
        return self._last_rate_limit

    # -- requests ---------------------------------------------------------

    def send(self, text: str) -> None:
        if self._turn is not None:
            raise BrainBusyError("A request is already running")
        turn = _Turn(
            deadline=self._clock() + self._settings.request_timeout,
            session_before=self._state.session_id,
            model_before=self._unconfirmed_model,
        )
        self._turn = turn
        if not self._network_check():
            self._fail(turn, BrainErrorKind.NETWORK, "Pas de connexion réseau.")
            return
        try:
            process = self._ensure_process()
            process.write({"type": "user", "message": {"role": "user", "content": text}})
        except (OSError, BrainUnavailableError) as exc:
            self._drop_process()
            self._fail(turn, BrainErrorKind.PROCESS_DIED, str(exc))

    def events(self) -> Iterator[BrainEvent]:
        while (turn := self._turn) is not None:
            event = self._next_event(turn)
            if event is None:
                continue
            if isinstance(event, TurnCompleted):
                event = self._finish(turn, event)
            else:
                self._observe(turn, event)
            yield event

    def interrupt(self) -> None:
        turn = self._turn
        if turn is None:
            return
        if turn.forced_error is None:
            turn.forced_error = BrainError(BrainErrorKind.INTERRUPTED, "Interrompu.")
        self._request_interrupt(turn)

    # -- session control --------------------------------------------------

    def set_model(self, alias: str) -> None:
        self._ensure_idle()
        if alias == self._state.model:
            return
        previous = self._state.model
        if self._process is not None and self._process.alive:
            # Switch inside the running session (local slash command, no quota used).
            self.send(f"/model {alias}")
            outcome = [e for e in self.events() if isinstance(e, TurnCompleted)]
            if outcome and outcome[-1].error is None:
                self._state.model = alias
                return
            self._drop_process()  # fall back to relaunching with --model and --resume
        self._state.model = alias
        self._unconfirmed_model = previous

    def set_mode(self, mode: Mode) -> None:
        self._ensure_idle()
        if mode is not self._state.mode:
            self._state.mode = mode
            self._drop_process()  # tools are fixed at launch: relaunch with --resume

    def new_session(self, name: str, mode: Mode, model: str) -> None:
        self._switch(SessionState(mode=mode, model=model, name=name))

    def resume_session(self, session_id: str, name: str, mode: Mode, model: str) -> None:
        self._switch(SessionState(mode=mode, model=model, name=name, session_id=session_id))

    def close(self) -> None:
        if self._turn is not None:
            self.interrupt()
        self._turn = None
        self._drop_process()

    # -- internals ----------------------------------------------------------

    def _ensure_idle(self) -> None:
        if self._turn is not None:
            raise BrainBusyError("A request is already running")

    def _switch(self, state: SessionState) -> None:
        self._ensure_idle()
        self._drop_process()
        self._state = state
        self._unconfirmed_model = None

    def _ensure_process(self) -> _Process:
        if self._process is not None and self._process.alive:
            return self._process
        self._drop_process()
        binary = self._which(self._settings.binary)
        if binary is None:
            raise BrainUnavailableError(f"'{self._settings.binary}' est introuvable dans le PATH.")
        self._settings.workspace.mkdir(parents=True, exist_ok=True)
        self._settings.runtime_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = self._settings.runtime_dir / "system-prompt.md"
        prompt = build_system_prompt(
            self._settings.persona,
            self._state.mode,
            self._now(),
            self._settings.user_names,
            self._state.name,
        )
        prompt_file.write_text(prompt, encoding="utf-8")
        settings_file = self._settings.runtime_dir / "claude-settings.json"
        settings_file.write_text(
            json.dumps(permission_settings(self._settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        command = build_command(binary, self._state, prompt_file, self._settings, settings_file)
        logger.info(
            "Starting claude: mode=%s model=%s resume=%s",
            self._state.mode,
            self._state.model,
            self._state.session_id,
        )
        handle = self._factory(command, build_env(os.environ), self._settings.workspace)
        self._process = _Process(handle)
        return self._process

    def _drop_process(self) -> None:
        process, self._process = self._process, None
        if process is not None:
            process.stop()

    def _fail(self, turn: _Turn, kind: BrainErrorKind, message: str) -> None:
        error = BrainError(kind, message)
        turn.pending.append(TurnCompleted("", self._state.session_id, error=error))

    def _next_event(self, turn: _Turn) -> BrainEvent | None:
        if turn.pending:
            return turn.pending.pop(0)
        now = self._clock()
        if turn.interrupt_deadline is not None and now >= turn.interrupt_deadline:
            logger.warning("claude ignored the interrupt, killing it")
            self._drop_process()
            error = turn.forced_error or BrainError(BrainErrorKind.INTERRUPTED)
            return TurnCompleted("", self._state.session_id, error=error)
        if turn.interrupt_deadline is None and now >= turn.deadline:
            turn.forced_error = BrainError(BrainErrorKind.TIMEOUT, "Délai de réponse dépassé.")
            self._request_interrupt(turn)
            return None
        process = self._process
        if process is None:
            error = turn.forced_error or BrainError(BrainErrorKind.PROCESS_DIED)
            return TurnCompleted("", self._state.session_id, error=error)
        try:
            item = process.queue.get(timeout=_POLL_SECONDS)
        except queue.Empty:
            return None
        if item is _EOF:
            self._process = None
            error = turn.forced_error or BrainError(
                BrainErrorKind.PROCESS_DIED, "Le processus claude s'est arrêté."
            )
            return TurnCompleted("", self._state.session_id, error=error)
        return item  # type: ignore[return-value]

    def _observe(self, turn: _Turn, event: BrainEvent) -> None:
        if isinstance(event, SessionStarted) and event.session_id:
            self._state.session_id = event.session_id
        elif isinstance(event, RateLimitStatus):
            self._last_rate_limit = event
        elif isinstance(event, ToolUse):
            actions_log.info("tool=%s input=%s", event.name, _short(event.input))
        elif isinstance(event, ApiRetry):
            kind = api_retry_error(event)
            if kind is not None and turn.forced_error is None:
                # Never let claude retry in a loop on quota, auth or network errors.
                turn.forced_error = BrainError(kind, event.error or "")
                self._request_interrupt(turn)

    def _finish(self, turn: _Turn, event: TurnCompleted) -> TurnCompleted:
        self._turn = None
        error = turn.forced_error or event.error
        if (
            error is not None
            and error.kind is BrainErrorKind.RATE_LIMIT
            and error.resets_at is None
        ):
            limit = self._last_rate_limit
            error = replace(error, resets_at=limit.resets_at if limit else None)
        if error is not None and error.kind is BrainErrorKind.MODEL_NOT_FOUND:
            # Stay on the previous model and session instead of the refused one.
            if turn.model_before is not None:
                self._state.model = turn.model_before
            self._state.session_id = turn.session_before
            self._drop_process()
        else:
            if event.session_id:
                self._state.session_id = event.session_id
            if error is None:
                self._unconfirmed_model = None
        for tool in event.permission_denials:
            actions_log.info("denied tool=%s", tool)
        return replace(event, error=error)

    def _request_interrupt(self, turn: _Turn) -> None:
        if turn.interrupt_deadline is not None:
            return
        turn.interrupt_deadline = self._clock() + INTERRUPT_GRACE_SECONDS
        process = self._process
        if process is None:
            return
        try:
            process.write(
                {
                    "type": "control_request",
                    "request_id": f"interrupt-{time.time_ns()}",
                    "request": {"subtype": "interrupt"},
                }
            )
        except OSError:
            logger.warning("Could not send interrupt to claude")


def _short(data: dict[str, Any], limit: int = 200) -> str:
    text = json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"
