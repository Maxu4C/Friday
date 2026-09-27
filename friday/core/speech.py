"""Turn Claude's streamed answer into sentences to speak and blocks to display.

Speech starts as soon as the first sentence is complete, while Claude is still
writing the rest. Technical content inside [AFFICHER]...[/AFFICHER] is never
spoken: it is handed to the display instead.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from friday.core.prompt import MODE_CODE_MARKER

DISPLAY_OPEN = "[AFFICHER]"
DISPLAY_CLOSE = "[/AFFICHER]"
MAX_SENTENCE = 250  # split longer runs at a comma so speech starts early

_ABBREVIATIONS = {
    "m", "mm", "mme", "mlle", "dr", "pr", "me", "st", "ste", "etc", "cf", "ex", "p", "vol",
    "env", "av", "apr", "fig", "ch", "art", "approx",
}  # fmt: skip
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"»”')\]]*\s+|\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s)")
_SOFT_BREAK = re.compile(r"[,;:]\s+")
_DISPLAY_BLOCK = re.compile(
    re.escape(DISPLAY_OPEN) + r".*?(?:" + re.escape(DISPLAY_CLOSE) + r"|$)", re.DOTALL
)
_CODE_FENCE = re.compile(r"```.*?(?:```|$)", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LINK = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")
_URL = re.compile(r"https?://\S+|www\.\S+")
_LINE_MARKUP = re.compile(r"^\s*(?:#{1,6}\s+|[-*•+]\s+|>\s*)", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*{1,3}|_{2,3}|~~)(.+?)\1")
_MISTER = re.compile(r"\bMr\b\.?")
_KEEP_SYMBOLS = {"°", "€", "£", "©", "®", "™", "§"}


@dataclass(frozen=True)
class Speak:
    text: str


@dataclass(frozen=True)
class Display:
    text: str


Segment = Speak | Display


def clean_for_speech(text: str) -> str:
    """What a human would read aloud: no markdown, code, URLs, emojis or markers."""
    text = text.replace(MODE_CODE_MARKER, " ")
    text = _DISPLAY_BLOCK.sub(" ", text)
    text = _CODE_FENCE.sub(" ", text)
    text = _INLINE_CODE.sub(r"\1", text)
    text = _LINK.sub(r"\1", text)
    text = _URL.sub("un lien", text)
    text = _LINE_MARKUP.sub("", text)
    text = _EMPHASIS.sub(r"\2", text)
    text = text.replace("|", " ").replace("*", " ").replace("#", " ")
    text = "".join(c for c in text if c in _KEEP_SYMBOLS or not _is_emoji(c))
    text = _MISTER.sub("Mister", text)
    return " ".join(text.split())


def _is_emoji(char: str) -> bool:
    if char in "‍️︎":
        return True
    return unicodedata.category(char) in ("So", "Sk", "Cs") and ord(char) > 0x2000


class SpeechStream:
    def __init__(self) -> None:
        self._buffer = ""
        self._in_display = False

    def feed(self, chunk: str) -> list[Segment]:
        self._buffer += chunk
        segments: list[Segment] = []
        while True:
            if self._in_display:
                end = self._buffer.find(DISPLAY_CLOSE)
                if end < 0:
                    break
                segments.append(Display(self._buffer[:end].strip("\n")))
                self._buffer = self._buffer[end + len(DISPLAY_CLOSE) :]
                self._in_display = False
                continue
            start = self._buffer.find(DISPLAY_OPEN)
            if start >= 0:
                segments += self._sentences(self._buffer[:start], final=True)
                self._buffer = self._buffer[start + len(DISPLAY_OPEN) :]
                self._in_display = True
                continue
            # Keep back a possible beginning of "[AFFICHER]" until the next chunk.
            cut = len(self._buffer) - _partial_suffix(self._buffer, DISPLAY_OPEN)
            sentences, rest = self._split(self._buffer[:cut])
            segments += sentences
            self._buffer = rest + self._buffer[cut:]
            break
        return segments

    def flush(self) -> list[Segment]:
        """End of the answer: whatever is left becomes the last segment."""
        buffer, self._buffer = self._buffer, ""
        if self._in_display:
            self._in_display = False
            return [Display(buffer.strip("\n"))] if buffer.strip() else []
        return self._sentences(buffer, final=True)

    def _sentences(self, text: str, *, final: bool) -> list[Segment]:
        sentences, rest = self._split(text)
        spoken = clean_for_speech(rest)
        if final and spoken:
            sentences.append(Speak(spoken))
        return sentences

    @staticmethod
    def _split(text: str) -> tuple[list[Segment], str]:
        segments: list[Segment] = []
        position = 0
        for match in _BOUNDARY.finditer(text):
            candidate = text[position : match.start()]
            if _ends_with_abbreviation(candidate):
                continue
            spoken = clean_for_speech(candidate)
            if spoken:
                segments.append(Speak(spoken))
            position = match.end()
        rest = text[position:]
        while len(rest) > MAX_SENTENCE:
            breaks = list(_SOFT_BREAK.finditer(rest, 0, MAX_SENTENCE))
            if not breaks:
                break
            cut = breaks[-1]
            spoken = clean_for_speech(rest[: cut.start() + 1])
            if spoken:
                segments.append(Speak(spoken))
            rest = rest[cut.end() :]
        return segments, rest


def _ends_with_abbreviation(sentence: str) -> bool:
    """ "M." or "etc." do not end a sentence, nor a list number such as "1."."""
    stripped = sentence.rstrip("\"»”')] ")
    if not stripped.endswith("."):
        return False
    words = stripped[:-1].split()
    if not words:
        return True
    last = words[-1].casefold()
    if last in _ABBREVIATIONS:
        return True
    return len(words) == 1 and (last.isdigit() or (len(last) == 1 and last.isalpha()))


def _partial_suffix(text: str, marker: str) -> int:
    """Length of the end of `text` that could be the beginning of `marker`."""
    for size in range(min(len(marker) - 1, len(text)), 0, -1):
        if marker.startswith(text[-size:]):
            return size
    return 0
