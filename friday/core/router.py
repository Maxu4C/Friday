"""Local choice between the simple and the complex model (no call to Claude)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from friday.core.events import Mode
from friday.core.text import normalize

_FILE = re.compile(
    r"\b[\w-]+\.(?:py|pyw|js|mjs|ts|tsx|jsx|java|kt|cs|cpp|cc|c|h|hpp|go|rs|php|rb|swift|json|"
    r"ya?ml|toml|ini|cfg|md|txt|csv|tsv|html?|css|scss|sql|ps1|psm1|bat|cmd|sh|xml|log|docx?|"
    r"xlsx?|pptx?|pdf|exe|dll|zip)\b",
    re.IGNORECASE,
)
_PATH = re.compile(r"[a-zA-Z]:[\\/]|\\\\|(?:^|\s)(?:\.{1,2}|~)?/[\w.-]+/|[\w-]+[\\/][\w.-]+[\\/]")
# Words that point at the computer, files or code: always the complex model.
_TECH_WORDS = (
    "fichier", "dossier", "repertoire", "projet", "code", "script", "fonction", "classe",
    "methode", "variable", "bug", "erreur", "exception", "stack", "commande", "terminal",
    "powershell", "programme", "logiciel", "repo", "depot", "git", "commit", "branche", "api",
    "serveur", "base de donnees", "sql", "docker", "python", "javascript", "typescript",
    "algorithme", "compiler", "compilation", "debug", "deboguer", "test unitaire",
    "fonctions", "classes", "methodes", "variables", "programmes", "logiciels", "commandes",
)  # fmt: skip


class ModelRole(StrEnum):
    SIMPLE = "simple"
    COMPLEX = "complex"


@dataclass(frozen=True)
class RouterRules:
    simple_max_words: int
    simple_patterns: tuple[str, ...]
    complex_patterns: tuple[str, ...]


@dataclass(frozen=True)
class Route:
    role: ModelRole
    reason: str


def _word_prefixes(patterns: tuple[str, ...]) -> re.Pattern[str] | None:
    """Match each pattern at a word start; its last word may be conjugated (crée -> créez)."""
    alternatives = [re.escape(normalize(p)) for p in patterns if normalize(p)]
    if not alternatives:
        return None
    return re.compile(r"(?:^| )(?:" + "|".join(alternatives) + r")\w*")


def _whole_words(words: tuple[str, ...]) -> re.Pattern[str]:
    """Match whole words, singular or plural ("repo" must not match "répondez")."""
    alternatives = "|".join(re.escape(normalize(w)) for w in words)
    return re.compile(r"(?:^| )(?:" + alternatives + r")[sx]?(?= |$)")


class Router:
    def __init__(self, rules: RouterRules) -> None:
        self._max_words = rules.simple_max_words
        self._simple = _word_prefixes(rules.simple_patterns)
        self._complex = _word_prefixes(rules.complex_patterns)
        self._tech = _whole_words(_TECH_WORDS)

    def route(self, text: str, mode: Mode) -> Route:
        if mode is Mode.CLAUDE_CODE:
            return Route(ModelRole.COMPLEX, "mode Claude Code")
        normalized = normalize(text)
        if _FILE.search(text) or _PATH.search(text):
            return Route(ModelRole.COMPLEX, "fichier ou chemin mentionné")
        if self._complex is not None and (match := self._complex.search(normalized)):
            return Route(ModelRole.COMPLEX, f"demande d'action ou de raisonnement : {match[0]}")
        if match := self._tech.search(normalized):
            return Route(ModelRole.COMPLEX, f"sujet technique : {match[0].strip()}")
        if len(normalized.split()) >= self._max_words:
            return Route(ModelRole.COMPLEX, "demande longue")
        if self._simple is not None and (match := self._simple.search(normalized)):
            return Route(ModelRole.SIMPLE, f"question simple : {match[0].strip()}")
        return Route(ModelRole.COMPLEX, "cas ambigu")
