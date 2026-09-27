"""Local routing between the simple (Haiku) and the complex (Opus) model."""

from pathlib import Path

import pytest

from friday.config import load_config
from friday.core.events import Mode
from friday.core.router import ModelRole, Router, RouterRules

ROUTER = Router(load_config(Path(__file__).parents[1] / "config" / "friday.example.yaml").router)

SIMPLE = [
    "Qu'est-ce que la photosynthèse ?",
    "C'est quoi un trou noir ?",
    "Combien de kilomètres entre Paris et Lyon ?",
    "Quelle heure est-il à Tokyo ?",
    "Traduis « bonjour » en japonais.",
    "Définis le mot résilience.",
    "Explique en une phrase la relativité.",
    "Qui est le président du Brésil ?",
    "Quand a eu lieu la bataille de Marignan ?",
    "Quelle est la capitale de l'Australie ?",
    "Que veut dire « serendipity » ?",
    "Comment dit-on merci en allemand ?",
    # "répondez" must not be taken for the technical word "repo"
    "Qu'est-ce que la photosynthèse ? Répondez en une phrase.",
    "Qui a écrit Les Misérables ? Réponds vite.",
]

COMPLEX = [
    # verbe d'action sur le PC ou demande de production
    "Crée un fichier notes.txt sur le bureau.",
    "Corrige le bug dans mon script.",
    "Ouvre le dossier Téléchargements.",
    "Exécute les tests du projet.",
    "Cherche dans mes documents la facture de mars.",
    "Analyse ce contrat et dis-moi les risques.",
    "Refactorise la classe Commande.",
    "Rédige un mail de relance pour mon client.",
    # fichier, chemin, code
    "Qu'est-ce que contient main.py ?",
    "C'est quoi le dossier C:\\Users\\maxch\\Friday ?",
    "Combien de lignes fait le fichier README ?",
    "Qu'est-ce qu'une fonction récursive en Python ?",
    "C'est quoi un repo Git ?",
    "Combien de fichiers dans mes Documents ?",
    # raisonnement
    "Compare React et Vue pour un petit site vitrine.",
    "Conçois une architecture pour une appli de réservation.",
    "Planifie ma semaine de révisions.",
    "Pourquoi ça plante quand je lance le serveur ?",
    # demande longue
    "Je voudrais que tu m'expliques en détail comment fonctionne le système immunitaire "
    "humain face à un virus, avec les différentes étapes de la réponse",
    # ambigu : mieux vaut une bonne réponse qu'une réponse rapide
    "Donne-moi ton avis sur mon idée de restaurant.",
    "Bonjour !",
    "Raconte-moi une histoire.",
]


@pytest.mark.parametrize("sentence", SIMPLE)
def test_simple_questions_go_to_the_simple_model(sentence: str) -> None:
    route = ROUTER.route(sentence, Mode.CLAUDE)
    assert route.role is ModelRole.SIMPLE, route.reason


@pytest.mark.parametrize("sentence", COMPLEX)
def test_other_requests_go_to_the_complex_model(sentence: str) -> None:
    route = ROUTER.route(sentence, Mode.CLAUDE)
    assert route.role is ModelRole.COMPLEX, route.reason


def test_claude_code_mode_always_uses_the_complex_model() -> None:
    route = ROUTER.route("Quelle heure est-il ?", Mode.CLAUDE_CODE)
    assert route.role is ModelRole.COMPLEX


def test_rules_are_editable() -> None:
    router = Router(RouterRules(5, ("raconte",), ()))
    assert router.route("Raconte une blague", Mode.CLAUDE).role is ModelRole.SIMPLE
    assert router.route("raconte une très longue histoire de pirates", Mode.CLAUDE).role is (
        ModelRole.COMPLEX
    )
