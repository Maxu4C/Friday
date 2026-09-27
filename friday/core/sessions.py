"""Registry of FRIDAY's named sessions (each one maps to a Claude Code session id)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from friday.core.events import Mode
from friday.core.text import levenshtein, normalize

FORMAT_VERSION = 1
MAX_NAME_DISTANCE = 2
_AUTO_NAME = re.compile(r"^session (\d+)$")
_DISPLAY_BLOCK = re.compile(r"\[AFFICHER\].*?(?:\[/AFFICHER\]|$)", re.DOTALL)
_MARKDOWN = re.compile(r"[*_`#>|]+")
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s")
SUMMARY_LENGTH = 100


class SessionNameTakenError(ValueError):
    pass


@dataclass
class SessionRecord:
    key: str
    name: str
    mode: Mode
    model: str
    workspace: str
    created_at: datetime
    last_used_at: datetime
    session_id: str | None = None
    model_lock: str | None = None  # model imposed by the user; None = automatic routing
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "session_id": self.session_id,
            "mode": self.mode.value,
            "model": self.model,
            "model_lock": self.model_lock,
            "workspace": self.workspace,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat(),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionRecord:
        return cls(
            key=str(data["key"]),
            name=str(data["name"]),
            session_id=data.get("session_id"),
            mode=Mode(data.get("mode", Mode.CLAUDE.value)),
            model=str(data["model"]),
            model_lock=data.get("model_lock"),
            workspace=str(data.get("workspace", "")),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_used_at=datetime.fromisoformat(data["last_used_at"]),
            summary=str(data.get("summary", "")),
        )


def summarize(answer: str) -> str:
    """One spoken-style line from Claude's last answer, for the session list."""
    text = _DISPLAY_BLOCK.sub(" ", answer)
    text = " ".join(_MARKDOWN.sub(" ", text).split())
    if not text:
        return ""
    sentence = _SENTENCE_END.split(text, maxsplit=1)[0]
    if len(sentence) <= SUMMARY_LENGTH:
        return sentence
    return sentence[: SUMMARY_LENGTH - 1].rstrip() + "…"


class SessionRegistry:
    def __init__(
        self,
        records: Iterable[SessionRecord] = (),
        current_key: str | None = None,
        key_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._records = {record.key: record for record in records}
        self._current = current_key if current_key in self._records else None
        self._new_key = key_factory

    # -- queries ---------------------------------------------------------------

    @property
    def records(self) -> list[SessionRecord]:
        """Most recently used first."""
        return sorted(self._records.values(), key=lambda r: r.last_used_at, reverse=True)

    @property
    def current(self) -> SessionRecord | None:
        return self._records.get(self._current) if self._current else None

    def previous(self) -> SessionRecord | None:
        return next((r for r in self.records if r.key != self._current), None)

    def find(self, query: str) -> list[SessionRecord]:
        """Tolerant lookup: accents, case, up to two typos, partial names, "3" for "Session 3".

        Several results mean the query is ambiguous.
        """
        wanted = normalize(query)
        if not wanted:
            return []
        if wanted.isdigit():
            wanted = f"session {wanted}"
        scored: list[tuple[int, SessionRecord]] = []
        for record in self._records.values():
            name = normalize(record.name)
            if name == wanted:
                return [record]
            distance = levenshtein(wanted, name)
            if distance <= MAX_NAME_DISTANCE:
                scored.append((distance, record))
            elif wanted in name.split() or (len(wanted) >= 3 and wanted in name):
                scored.append((MAX_NAME_DISTANCE + 1, record))
        if not scored:
            return []
        best = min(score for score, _ in scored)
        return [record for score, record in sorted(scored, key=lambda s: s[0]) if score == best]

    # -- changes -------------------------------------------------------------------

    def create(
        self, name: str | None, mode: Mode, model: str, workspace: str, now: datetime
    ) -> SessionRecord:
        name = (name or "").strip() or self._auto_name()
        self._check_free(name)
        record = SessionRecord(
            key=self._new_key(),
            name=name,
            mode=mode,
            model=model,
            workspace=workspace,
            created_at=now,
            last_used_at=now,
        )
        self._records[record.key] = record
        self._current = record.key
        return record

    def import_session(
        self,
        name: str,
        session_id: str,
        model: str,
        workspace: str,
        last_used_at: datetime,
        summary: str = "",
    ) -> SessionRecord:
        """Add a Claude Code session started outside FRIDAY, without switching to it.

        A taken name gets a number ("site 2"); importing twice returns the existing record.
        """
        for record in self._records.values():
            if record.session_id == session_id:
                return record
        base = name.strip() or self._auto_name()
        name, number = base, 1
        while self._name_taken(name):
            number += 1
            name = f"{base} {number}"
        record = SessionRecord(
            key=self._new_key(),
            name=name,
            mode=Mode.CLAUDE_CODE,  # a terminal session had its tools
            model=model,
            workspace=workspace,
            created_at=last_used_at,
            last_used_at=last_used_at,
            session_id=session_id,
            summary=summary,
        )
        self._records[record.key] = record
        return record

    def has_session_id(self, session_id: str) -> bool:
        return any(record.session_id == session_id for record in self._records.values())

    def activate(self, record: SessionRecord, now: datetime) -> None:
        self._current = record.key
        record.last_used_at = now

    def rename(self, record: SessionRecord, name: str) -> None:
        name = name.strip()
        if not name:
            raise SessionNameTakenError("Le nom de session ne peut pas être vide.")
        self._check_free(name, ignore=record)
        record.name = name

    def forget(self, record: SessionRecord) -> None:
        self._records.pop(record.key, None)
        if self._current == record.key:
            self._current = None

    # -- persistence -----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": FORMAT_VERSION,
            "current": self._current,
            "sessions": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SessionRegistry:
        if not data:
            return cls()
        records = [SessionRecord.from_dict(item) for item in data.get("sessions", [])]
        return cls(records, data.get("current"))

    # -- internals -------------------------------------------------------------------

    def _auto_name(self) -> str:
        numbers = [
            int(match[1])
            for record in self._records.values()
            if (match := _AUTO_NAME.match(normalize(record.name)))
        ]
        return f"Session {max(numbers, default=0) + 1}"

    def _name_taken(self, name: str, ignore: SessionRecord | None = None) -> SessionRecord | None:
        wanted = normalize(name)
        return next(
            (
                record
                for record in self._records.values()
                if record is not ignore and normalize(record.name) == wanted
            ),
            None,
        )

    def _check_free(self, name: str, ignore: SessionRecord | None = None) -> None:
        taken = self._name_taken(name, ignore)
        if taken is not None:
            raise SessionNameTakenError(f"Une session s'appelle déjà {taken.name}.")
