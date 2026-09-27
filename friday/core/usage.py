"""Count requests sent to Claude, per model and per hour, to watch the plan's quota."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

KEEP_DAYS = 31


def _hour_key(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H")


class UsageCounter:
    def __init__(self, hours: dict[str, dict[str, int]] | None = None) -> None:
        self._hours: dict[str, Counter[str]] = {
            key: Counter(counts) for key, counts in (hours or {}).items()
        }

    def record(self, model: str, now: datetime) -> None:
        self._hours.setdefault(_hour_key(now), Counter())[model] += 1
        oldest = _hour_key(now - timedelta(days=KEEP_DAYS))
        for key in [k for k in self._hours if k < oldest]:
            del self._hours[key]

    def day(self, day: date) -> Counter[str]:
        prefix = day.isoformat()
        total: Counter[str] = Counter()
        for key, counts in self._hours.items():
            if key.startswith(prefix):
                total.update(counts)
        return total

    def hour(self, now: datetime) -> Counter[str]:
        return Counter(self._hours.get(_hour_key(now), Counter()))

    def to_dict(self) -> dict[str, Any]:
        return {"hours": {key: dict(counts) for key, counts in sorted(self._hours.items())}}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageCounter:
        return cls((data or {}).get("hours"))
