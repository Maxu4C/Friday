"""Protocol §3.5 example sentences (and transcription variants) are recognized locally."""

import pytest

from friday.core.events import Mode
from friday.core.intents import (
    AskMode,
    AskModel,
    AskUsage,
    AutoModel,
    Cancel,
    CurrentSession,
    ForgetSession,
    Intent,
    IntentParser,
    ListSessions,
    MuteMic,
    NewSession,
    OpenClaudeWeb,
    RenameSession,
    Repeat,
    ResumeSession,
    SetMode,
    SetModel,
    Stop,
    Unclear,
)

PARSER = IntentParser(
    {
        "haiku": ["haiku", "aïcou", "aiku"],
        "opus": ["opus", "opus 5.5", "opus cinq cinq"],
        "fable": ["fable", "fable 5.1", "fable cinq un"],
    }
)

CODE, CLAUDE = Mode.CLAUDE_CODE, Mode.CLAUDE

EXPECTED: list[tuple[str, Intent]] = [
    # Changer de modèle
    ("utilise Opus", SetModel("opus")),
    ("Passe sur Haiku.", SetModel("haiku")),
    ("prends Fable 5.1", SetModel("fable")),
    ("avec Fable", SetModel("fable")),
    ("Utilisez Opus s'il vous plaît", SetModel("opus")),
    ("passez sur opus cinq cinq", SetModel("opus")),
    ("utilise aïcou", SetModel("haiku")),
    ("passe sur aiku", SetModel("haiku")),
    ("Friday, change de modèle pour Fable", SetModel("fable")),
    ("tu peux passer sur le modèle Opus ?", SetModel("opus")),
    ("modèle automatique", AutoModel()),
    ("repasse en modèle automatique", AutoModel()),
    ("choisis le modèle toi-même", AutoModel()),
    # Changer de mode
    ("passe en mode Claude Code", SetMode(CODE)),
    ("Friday, passe en mode Claude Code.", SetMode(CODE)),
    ("passe en mode cloud code", SetMode(CODE)),
    ("passez en mode clode code", SetMode(CODE)),
    ("repasse sur Claude", SetMode(CLAUDE)),
    ("mode conversation", SetMode(CLAUDE)),
    ("mode action", SetMode(CODE)),
    ("mets-toi en mode code", SetMode(CODE)),
    ("reviens en mode conversation", SetMode(CLAUDE)),
    # Sessions
    ("nouvelle session", NewSession()),
    ("Nouvelle session pour le projet boucherie", NewSession("boucherie")),
    ("crée une nouvelle session appelée Site Restaurant", NewSession("Site Restaurant")),
    ("reprends la session boucherie", ResumeSession("boucherie")),
    ("Tu peux reprendre la session « Boucherie » ?", ResumeSession("Boucherie")),
    ("reprenez la session du projet Boucherie", ResumeSession("Boucherie")),
    ("retourne sur la session précédente", ResumeSession(None)),
    ("session précédente", ResumeSession(None)),
    ("liste mes sessions", ListSessions()),
    ("quelles sessions j'ai ?", ListSessions()),
    ("montre-moi les sessions", ListSessions()),
    ("renomme cette session en site restaurant", RenameSession("site restaurant")),
    ("oublie la session boucherie", ForgetSession("boucherie")),
    ("oublie cette session", ForgetSession(None)),
    ("sur quelle session on est ?", CurrentSession()),
    ("on est sur quelle session", CurrentSession()),
    # État
    ("quel modèle tu utilises ?", AskModel()),
    ("vous utilisez quel modèle ?", AskModel()),
    ("on est dans quel mode ?", AskMode()),
    ("quel mode ?", AskMode()),
    ("combien de requêtes aujourd'hui ?", AskUsage()),
    ("combien de requêtes j'ai fait aujourd'hui", AskUsage()),
    # Contrôle
    ("stop", Stop()),
    ("Stop !", Stop()),
    ("arrête", Stop()),
    ("tais-toi", Stop()),
    ("annule", Cancel()),
    ("laisse tomber", Cancel()),
    ("répète", Repeat()),
    ("tu peux répéter ?", Repeat()),
    ("coupe le micro", MuteMic()),
    ("ouvre Claude dans le navigateur", OpenClaudeWeb()),
    ("ouvre claude.ai", OpenClaudeWeb()),
]


@pytest.mark.parametrize(("sentence", "expected"), EXPECTED)
def test_system_command(sentence: str, expected: Intent) -> None:
    assert PARSER.parse(sentence) == expected


@pytest.mark.parametrize(
    "sentence",
    [
        "explique-moi la photosynthèse",
        "c'est quoi un modèle de langage ?",
        "quel modèle de voiture est le plus fiable",
        "crée un fichier notes.txt",
        "passe-moi le sel",
        "quelle est la capitale de l'Australie ?",
        "arrête de me vouvoyer et explique-moi les sessions HTTP",
        "résume la session d'hier",
        "",
        "   ",
    ],
)
def test_ordinary_requests_go_to_claude(sentence: str) -> None:
    assert PARSER.parse(sentence) is None


def test_command_followed_by_a_request_keeps_the_request_intact() -> None:
    assert PARSER.parse("utilise Opus pour analyser l'erreur du fichier main.py") == SetModel(
        "opus", "analyser l'erreur du fichier main.py"
    )
    assert PARSER.parse("passe en mode code et crée un fichier « notes.txt »") == SetMode(
        CODE, "crée un fichier « notes.txt »"
    )


@pytest.mark.parametrize(
    ("sentence", "guess"),
    [
        ("Opus ?", SetModel("opus")),
        ("et Haiku", SetModel("haiku")),
        ("session boucherie", ResumeSession("boucherie")),
    ],
)
def test_near_commands_are_confirmed_first(sentence: str, guess: object) -> None:
    assert PARSER.parse(sentence) == Unclear(guess)  # type: ignore[arg-type]
