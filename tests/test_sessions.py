import itertools
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from friday.adapters.json_store import JsonFile
from friday.core.events import Mode
from friday.core.sessions import SessionNameTakenError, SessionRegistry, summarize
from friday.core.usage import UsageCounter

T0 = datetime(2026, 9, 27, 10, 0)


def registry() -> SessionRegistry:
    counter = itertools.count(1)
    return SessionRegistry(key_factory=lambda: f"k{next(counter)}")


def create(reg: SessionRegistry, name: str | None, minutes: int = 0) -> str:
    record = reg.create(name, Mode.CLAUDE, "opus", "C:/ws", T0 + timedelta(minutes=minutes))
    return record.name


def test_automatic_names_follow_each_other() -> None:
    reg = registry()
    assert [create(reg, None), create(reg, None), create(reg, "Boucherie"), create(reg, None)] == [
        "Session 1",
        "Session 2",
        "Boucherie",
        "Session 3",
    ]


def test_new_session_becomes_current() -> None:
    reg = registry()
    create(reg, "Boucherie")
    create(reg, "Site restaurant", 1)
    assert reg.current is not None and reg.current.name == "Site restaurant"
    previous = reg.previous()
    assert previous is not None and previous.name == "Boucherie"


def test_names_are_unique_ignoring_case_and_accents() -> None:
    reg = registry()
    create(reg, "Épicerie")
    with pytest.raises(SessionNameTakenError):
        create(reg, "epicerie")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("boucherie", "Boucherie"),
        ("BOUCHERIE", "Boucherie"),
        ("bouchrie", "Boucherie"),  # one typo
        ("boucheri", "Boucherie"),
        ("site", "Site restaurant"),  # partial name
        ("site restaurent", "Site restaurant"),
        ("épicerie fine", "Epicerie fine"),
        ("3", "Session 3"),
        ("session trois", None),
        ("garage", None),
    ],
)
def test_tolerant_lookup(query: str, expected: str | None) -> None:
    reg = registry()
    for name in ("Boucherie", "Site restaurant", "Epicerie fine", "Session 3"):
        create(reg, name)
    found = reg.find(query)
    assert [r.name for r in found] == ([expected] if expected else [])


def test_ambiguous_lookup_returns_every_candidate() -> None:
    reg = registry()
    create(reg, "Site restaurant")
    create(reg, "Site boucherie")
    assert {r.name for r in reg.find("site")} == {"Site restaurant", "Site boucherie"}


def test_rename_and_forget() -> None:
    reg = registry()
    create(reg, "A")
    create(reg, "B", 1)
    b = reg.current
    assert b is not None
    reg.rename(b, "Site restaurant")
    assert reg.find("site restaurant") == [b]
    with pytest.raises(SessionNameTakenError):
        reg.rename(b, "a")
    reg.forget(b)
    assert reg.current is None and [r.name for r in reg.records] == ["A"]


def test_records_are_sorted_by_last_use() -> None:
    reg = registry()
    create(reg, "Ancienne")
    create(reg, "Récente", 5)
    old = reg.find("ancienne")[0]
    reg.activate(old, T0 + timedelta(minutes=10))
    assert [r.name for r in reg.records] == ["Ancienne", "Récente"]


def test_persistence_round_trip(tmp_path: Path) -> None:
    reg = registry()
    create(reg, "Boucherie")
    record = reg.current
    assert record is not None
    record.session_id, record.model_lock, record.summary = "sid", "fable", "Menu de la semaine."
    store = JsonFile(tmp_path / "data" / "sessions.json")
    store.save(reg.to_dict())

    raw = json.loads((tmp_path / "data" / "sessions.json").read_text(encoding="utf-8"))
    assert raw["version"] == 1 and raw["sessions"][0]["created_at"] == "2026-09-27T10:00:00"

    loaded = SessionRegistry.from_dict(store.load())
    assert loaded.current is not None
    assert loaded.current.to_dict() == record.to_dict()


def test_corrupted_file_is_set_aside(tmp_path: Path) -> None:
    path = tmp_path / "sessions.json"
    path.write_text("{pas du json", encoding="utf-8")
    assert JsonFile(path).load() is None
    assert (tmp_path / "sessions.json.corrompu").exists()


@pytest.mark.parametrize(
    ("answer", "summary"),
    [
        ("Voilà le menu. Je l'ai affiché.", "Voilà le menu."),
        ("**Gras** et `code` ici.", "Gras et code ici."),
        ("C'est fait.\n[AFFICHER]\nfichier.txt\n[/AFFICHER]", "C'est fait."),
        ("[AFFICHER]seulement de l'affichage[/AFFICHER]", ""),
        ("mot " * 60, ("mot " * 60)[:99].rstrip() + "…"),
    ],
)
def test_summary(answer: str, summary: str) -> None:
    assert summarize(answer) == summary


def test_usage_counter_per_day_and_hour() -> None:
    usage = UsageCounter()
    usage.record("haiku", T0)
    usage.record("haiku", T0 + timedelta(minutes=5))
    usage.record("opus", T0 + timedelta(hours=2))
    usage.record("opus", T0 - timedelta(days=1))
    assert usage.day(date(2026, 9, 27)) == {"haiku": 2, "opus": 1}
    assert usage.hour(T0) == {"haiku": 2}
    restored = UsageCounter.from_dict(json.loads(json.dumps(usage.to_dict())))
    assert restored.day(date(2026, 9, 26)) == {"opus": 1}


def test_usage_counter_forgets_old_days() -> None:
    usage = UsageCounter()
    usage.record("opus", T0 - timedelta(days=40))
    usage.record("opus", T0)
    assert list(usage.to_dict()["hours"]) == ["2026-09-27T10"]
