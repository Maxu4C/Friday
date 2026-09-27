"""Reject what Whisper invents on silence or noise before it reaches Claude."""

from __future__ import annotations

from friday.core.text import normalize

# Classic Whisper hallucinations on silence (French subtitles seen in its training data).
_HALLUCINATIONS = (
    "sous titrage",
    "sous titres realises par",
    "sous titres par",
    "merci d avoir regarde",
    "merci de nous avoir regarde",
    "merci de votre attention",
    "abonnez vous",
    "n oubliez pas de vous abonner",
    "amara org",
    "radio canada",
    "societe radio canada",
    "st 501",
    "untertitel",
    "thanks for watching",
)
_MAX_HALLUCINATION_WORDS = 10


def clean_transcript(text: str) -> str | None:
    """The sentence to use, or None if nothing meaningful was heard."""
    text = " ".join(text.split()).strip(" .…-–—")
    normalized = normalize(text)
    if len(normalized.replace(" ", "")) < 2:
        return None
    words = normalized.split()
    if len(words) <= _MAX_HALLUCINATION_WORDS and any(h in normalized for h in _HALLUCINATIONS):
        return None
    if len(set(words)) == 1 and len(words) > 3:  # "merci merci merci merci"
        return None
    return text
