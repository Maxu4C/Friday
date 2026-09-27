"""Text helpers shared by the local (no Claude) language features."""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w]+")
_YES = {
    "oui", "ouais", "ouai", "yes", "ok", "okay", "d accord", "vas y", "allez y", "bien sur",
    "exactement", "absolument", "oui vas y", "oui allez y", "oui confirme", "confirme",
    "c est ca", "tout a fait", "affirmatif", "oui s il vous plait", "oui merci",
}  # fmt: skip
_NO = {
    "non", "nan", "no", "non merci", "pas maintenant", "laisse tomber", "annule", "negatif",
    "surtout pas", "non pas du tout",
}  # fmt: skip


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Lowercase, no accents, punctuation as spaces, single spaces."""
    cleaned = _NON_WORD.sub(" ", strip_accents(text).casefold().replace("_", " "))
    return " ".join(cleaned.split())


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            )
        previous = current
    return previous[-1]


def is_yes(text: str) -> bool:
    return normalize(text) in _YES


def is_no(text: str) -> bool:
    return normalize(text) in _NO


class MarkerFilter:
    """Hide a marker from streamed text, even when split across several chunks."""

    def __init__(self, marker: str) -> None:
        self._marker = marker
        self._held = ""
        self.seen = False

    def feed(self, text: str) -> str:
        data = self._held + text
        if self._marker in data:
            data = data.replace(self._marker, "")
            self.seen = True
        keep = 0
        for size in range(min(len(self._marker) - 1, len(data)), 0, -1):
            if self._marker.startswith(data[-size:]):
                keep = size
                break
        self._held = data[len(data) - keep :] if keep else ""
        return data[: len(data) - keep]

    def flush(self) -> str:
        held, self._held = self._held, ""
        return held
