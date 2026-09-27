"""System prompt appended to every claude session launched by FRIDAY."""

from __future__ import annotations

from datetime import datetime

from friday.core.events import Mode

# Emitted by Claude in conversation mode when the request needs the computer.
MODE_CODE_MARKER = "[MODE_CODE]"
# Prefixed to a request replayed right after switching to Claude Code mode.
MODE_CODE_ENABLED_NOTE = (
    "(Note de FRIDAY : l'utilisateur vient d'accepter de passer en mode Claude Code, "
    "tu as maintenant accès aux outils. Réalise sa demande précédente.)"
)

_DAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip

_MODE_RULES = {
    Mode.CLAUDE: (
        "Mode actuel : conversation. Tu n'as accès à aucun outil ni à l'ordinateur. "
        "Discute, réponds aux questions, aide à réfléchir et à rédiger. "
        "Si l'utilisateur demande une action sur l'ordinateur (fichiers, commandes, "
        "code à exécuter, applications), ne prétends pas l'avoir faite : dis en une phrase "
        "qu'il faut passer en mode Claude Code, puis termine ta réponse par le marqueur "
        f"{MODE_CODE_MARKER} seul, "
        "que FRIDAY retire avant la lecture."
    ),
    Mode.CLAUDE_CODE: (
        "Mode actuel : Claude Code. Tu peux agir sur l'ordinateur avec tes outils, dans le dossier "
        "de travail. Avant une action longue, annonce-la en une phrase. Après avoir agi, résume "
        "oralement ce que tu as fait et mets les détails (chemins, sorties, code) dans un bloc "
        "[AFFICHER]. Certaines actions peuvent être refusées : explique alors simplement ce qui "
        "n'a pas pu être fait. Les échanges précédents de cette session ont pu avoir lieu en mode "
        "conversation, sans outils : c'était normal d'y proposer le mode Claude Code, ne t'en "
        "excuse pas."
    ),
}


def french_datetime(now: datetime) -> str:
    return (
        f"{_DAYS[now.weekday()]} {now.day} {_MONTHS[now.month - 1]} {now.year}, "
        f"{now.hour} h {now.minute:02d}"
    )


def build_system_prompt(
    persona: str,
    mode: Mode,
    now: datetime,
    user_names: tuple[str, ...],
    session_name: str,
) -> str:
    names = " ou ".join(f"« {name} »" for name in user_names)
    context = (
        "## Contexte de session\n\n"
        f"- Date et heure : {french_datetime(now)}.\n"
        f"- Appelle l'utilisateur {names}.\n"
        f"- Session : {session_name}.\n\n"
        f"{_MODE_RULES[mode]}\n"
    )
    return f"{persona.strip()}\n\n{context}"


def strip_mode_marker(text: str) -> tuple[str, bool]:
    """Remove the mode-switch marker; report whether Claude suggested Claude Code mode."""
    if MODE_CODE_MARKER not in text:
        return text, False
    return text.replace(MODE_CODE_MARKER, "").rstrip(), True
