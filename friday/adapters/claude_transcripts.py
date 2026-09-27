"""Read-only listing of the Claude Code sessions started elsewhere (e.g. in a terminal),
from the transcripts in ~/.claude/projects, so FRIDAY can resume them."""

from __future__ import annotations

import json
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_ROOT = Path.home() / ".claude" / "projects"
# Sessions run in the temp folder are tools and scratch runs, not projects to resume.
SKIPPED_FOLDERS = (Path(tempfile.gettempdir()),)
_SCANNED_LINES = 400  # the first prompt and the folder are near the top
_PROMPT_LENGTH = 90


@dataclass(frozen=True)
class ClaudeTranscript:
    session_id: str
    cwd: str
    first_prompt: str
    last_used_at: datetime


def scan(
    root: Path = DEFAULT_ROOT, limit: int = 15, skipped: tuple[Path, ...] = SKIPPED_FOLDERS
) -> list[ClaudeTranscript]:
    """Most recent sessions first. Files are only read, never modified."""
    skipped_prefixes = tuple(str(folder).lower().rstrip("\\") + "\\" for folder in skipped)
    try:
        files = sorted(root.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError as exc:
        logger.warning("Cannot list %s: %s", root, exc)
        return []
    found: list[ClaudeTranscript] = []
    for path in files:
        transcript = read(path)
        if transcript is not None and not (transcript.cwd.lower() + "\\").startswith(
            skipped_prefixes
        ):
            found.append(transcript)
            if len(found) >= limit:
                break
    return found


def read(path: Path) -> ClaudeTranscript | None:
    session_id, cwd, prompt = path.stem, "", ""
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for number, line in enumerate(lines):
                if number >= _SCANNED_LINES or (cwd and prompt):
                    break
                record = _parse(line)
                if record is None or record.get("isSidechain"):
                    continue
                cwd = cwd or str(record.get("cwd") or "")
                session_id = str(record.get("sessionId") or session_id)
                if not prompt and record.get("type") == "user" and not record.get("isMeta"):
                    if record.get("turnOrigin", "human") != "human":
                        return None  # scripted run (claude -p, summaries...), not a person
                    prompt = _prompt_text(record.get("message"))
        modified = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError as exc:
        logger.warning("Unreadable transcript %s: %s", path.name, exc)
        return None
    if not cwd or not prompt:
        return None  # empty session, or not one a person started
    return ClaudeTranscript(session_id, cwd, _shorten(prompt), modified)


def _parse(line: str) -> dict[str, Any] | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


def _prompt_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, list):
        content = " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    text = " ".join(str(content or "").split())
    # Slash commands, command output and hook notes are wrapped in tags: not a prompt.
    return "" if text.startswith("<") else text


def _shorten(text: str) -> str:
    return text if len(text) <= _PROMPT_LENGTH else text[: _PROMPT_LENGTH - 1].rstrip() + "…"
