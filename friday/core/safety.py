"""Safety policy for actions Claude Code asks permission for (protocol §4.4).

Every action that reaches FRIDAY needs a spoken "oui". Destructive or
irreversible actions (blacklist below) need a second, explicit "oui, confirme".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from friday.core.text import normalize


class Risk(StrEnum):
    CONFIRM = "confirm"  # one "oui"
    DANGEROUS = "dangerous"  # "oui" then "oui, confirme"


@dataclass(frozen=True)
class Assessment:
    risk: Risk
    spoken: str  # short sentence FRIDAY reads aloud
    detail: str  # full action shown on screen
    reason: str = ""  # why it is dangerous


# (pattern, reason) — matched case-insensitively on the command or file path.
_DANGEROUS: tuple[tuple[str, str], ...] = (
    (r"remove-item\b.*-(?:recurse|r)\b", "suppression récursive"),
    (r"\b(?:rm|ri|del|erase|rd|rmdir)\b.*(?:-(?:recurse|r|rf|fr)\b|/s\b)", "suppression récursive"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "suppression récursive forcée"),
    (r"\bformat(?:-volume)?\b", "formatage d'un disque"),
    (r"\bclear-disk\b|\bdiskpart\b|\binitialize-disk\b", "modification des disques"),
    (r"\breg(?:\.exe)?\s+(?:delete|add|import)\b", "modification du registre"),
    (r"(?:set|new|remove|rename)-itemproperty\b|\bhk(?:lm|cu|cr|u|cc):",
     "modification du registre"),
    (r"\bshutdown\b|\bstop-computer\b|\brestart-computer\b", "extinction ou redémarrage"),
    (r"\buninstall-(?:package|module)\b|\bmsiexec\b.*\s/x\b"
     r"|\b(?:winget|choco|scoop)\s+uninstall\b", "désinstallation"),
    (r"\bsend-mailmessage\b|\bsmtp\b|\bmailto:", "envoi d'un e-mail ou d'un message"),
    (r"c:[\\/]+windows\b|%windir%|\$env:windir|%systemroot%|\$env:systemroot", "dossier Windows"),
    (r"\bbcdedit\b|\btakeown\b|\bicacls\b.*/grant", "réglages système ou droits d'accès"),
    (r"\bgit\s+(?:push\s+.*--force|push\s+-f|reset\s+--hard|clean\s+-[a-z]*f)",
     "perte de travail git"),
)  # fmt: skip
_DANGEROUS_RE = [(re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in _DANGEROUS]

_TOOL_LABELS = {
    "PowerShell": "une commande PowerShell",
    "Bash": "une commande",
    "Write": "écrire le fichier",
    "Edit": "modifier le fichier",
    "Read": "lire le fichier",
    "WebFetch": "consulter une page web",
    "WebSearch": "faire une recherche web",
}
_SPOKEN_LIMIT = 90


def assess(tool: str, tool_input: dict[str, Any], description: str = "") -> Assessment:
    target = _target(tool, tool_input)
    reason = next((why for pattern, why in _DANGEROUS_RE if pattern.search(target)), "")
    label = _TOOL_LABELS.get(tool, f"utiliser l'outil {tool}")
    what = description.strip() or _short(target)
    if tool in ("Write", "Edit", "Read"):
        spoken = f"Je dois {label} {_short(_file_name(target))}"
    else:
        spoken = f"Je dois exécuter {label} : {_short(what)}"
    detail = f"{tool} : {target}" if target else tool
    return Assessment(Risk.DANGEROUS if reason else Risk.CONFIRM, spoken, detail, reason)


def is_final_confirmation(answer: str) -> bool:
    """Second step of a dangerous action: an explicit "confirme" is required."""
    words = normalize(answer).split()
    return "confirme" in words or "confirmer" in words or "confirmez" in words


def _target(tool: str, tool_input: dict[str, Any]) -> str:
    for key in ("command", "file_path", "path", "url", "query", "pattern"):
        if key in tool_input and tool_input[key]:
            return str(tool_input[key])
    return ""


def _file_name(path: str) -> str:
    return re.split(r"[\\/]", path.rstrip("\\/"))[-1] or path


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _SPOKEN_LIMIT else text[: _SPOKEN_LIMIT - 1] + "…"
