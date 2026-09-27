"""Controller: local commands, routing, sessions, questions — without any real Claude call."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from friday.config import load_config
from friday.core.controller import Ask, Controller, ControllerSettings, Output, Say, ShowSessions
from friday.core.events import BrainError, BrainErrorKind, Mode, TextDelta
from friday.core.intents import IntentParser
from friday.core.prompt import MODE_CODE_ENABLED_NOTE
from friday.core.router import Router
from tests.fakes import FakeBrain, MemoryStore, Reply, answer

CONFIG = load_config(Path(__file__).parents[1] / "config" / "friday.example.yaml")
PARSER = IntentParser({a: i.spoken for a, i in CONFIG.models.available.items()})
ROUTER = Router(CONFIG.router)
SETTINGS = ControllerSettings(
    model_labels={a: i.label for a, i in CONFIG.models.available.items()},
    simple_model="haiku",
    complex_model="opus",
    default_mode=Mode.CLAUDE,
    workspace=Path("C:/ws"),
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 27, 10, 0)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class Harness:
    def __init__(
        self,
        replies: list[Reply] | None = None,
        sessions: MemoryStore | None = None,
        usage: MemoryStore | None = None,
    ) -> None:
        self.brain = FakeBrain(replies)
        self.sessions = sessions or MemoryStore()
        self.usage = usage or MemoryStore()
        self.opened: list[str] = []
        self.controller = Controller(
            self.brain,
            PARSER,
            ROUTER,
            SETTINGS,
            self.sessions,
            self.usage,
            now=Clock(),
            open_url=self.opened.append,
        )
        self.started = list(self.controller.start())

    def run(self, *texts: str) -> list[Output]:
        outputs: list[Output] = []
        for text in texts:
            outputs.extend(self.controller.handle(text))
        return outputs


def said(outputs: Iterable[Output]) -> list[str]:
    return [o.text for o in outputs if isinstance(o, Say | Ask)]


def streamed(outputs: Iterable[Output]) -> str:
    return "".join(o.text for o in outputs if isinstance(o, TextDelta))


# -- start and local commands ---------------------------------------------------------


def test_first_start_creates_and_announces_a_session() -> None:
    h = Harness()
    assert said(h.started) == [
        "Bonjour. Nouvelle session : Session 1, mode Claude, modèle automatique."
    ]
    assert h.brain.calls == ["new:Session 1"]


def test_system_commands_never_reach_claude() -> None:
    h = Harness()
    h.run(
        "utilise Opus",
        "modèle automatique",
        "passe en mode Claude Code",
        "repasse sur Claude",
        "nouvelle session pour le projet boucherie",
        "liste mes sessions",
        "sur quelle session on est ?",
        "quel modèle tu utilises ?",
        "on est dans quel mode ?",
        "combien de requêtes aujourd'hui ?",
        "renomme cette session en site restaurant",
        "stop",
        "répète",
    )
    assert h.brain.sent == []


# -- routing and model lock -----------------------------------------------------------


def test_router_picks_haiku_for_simple_questions_and_opus_otherwise() -> None:
    h = Harness()
    h.run("Quelle heure est-il à Tokyo ?", "Corrige le bug dans mon script.")
    assert [model for _, model, _ in h.brain.sent] == ["haiku", "opus"]


def test_locked_model_wins_until_automatic_again() -> None:
    h = Harness()
    outputs = h.run("utilise Fable")
    assert said(outputs) == ["Je passe sur Fable 5.1."]
    h.run("Quelle heure est-il ?")
    h.run("modèle automatique", "Quelle heure est-il ?")
    assert [model for _, model, _ in h.brain.sent] == ["fable", "haiku"]


def test_model_command_followed_by_a_request() -> None:
    h = Harness()
    outputs = h.run("utilise Opus pour m'expliquer la photosynthèse")
    assert said(outputs)[0] == "Je passe sur Opus 5.5."
    assert h.brain.sent == [("m'expliquer la photosynthèse", "opus", Mode.CLAUDE)]


def test_claude_code_mode_uses_the_complex_model() -> None:
    h = Harness()
    h.run("utilise Haiku", "modèle automatique")
    outputs = h.run("passe en mode Claude Code")
    assert said(outputs) == ["Je passe en mode Claude Code. Je passe sur Opus 5.5."]
    h.run("Quelle heure est-il ?")
    assert h.brain.sent[-1][1:] == ("opus", Mode.CLAUDE_CODE)


# -- questions ---------------------------------------------------------------------------


def test_action_request_offers_claude_code_mode() -> None:
    h = Harness([answer("Il faut le mode Claude Code. ", "[MODE", "_CODE]"), answer("C'est fait.")])
    outputs = h.run("Crée un fichier notes.txt")
    assert "[MODE_CODE]" not in streamed(outputs)
    assert said(outputs) == ["Voulez-vous que je passe en mode Claude Code ?"]
    outputs = h.run("oui")
    assert said(outputs)[0].startswith("Je passe en mode Claude Code.")
    assert h.brain.sent[-1] == (
        f"{MODE_CODE_ENABLED_NOTE}\nCrée un fichier notes.txt",
        "opus",
        Mode.CLAUDE_CODE,
    )
    assert h.controller.current.mode is Mode.CLAUDE_CODE


def test_declined_or_ignored_question() -> None:
    h = Harness([answer("Il faut le mode Claude Code. [MODE_CODE]")] * 2)
    assert said(h.run("Crée un fichier", "non"))[-1] == "D'accord, je reste en mode Claude."
    h.run("Crée un autre fichier")
    h.run("Quelle heure est-il ?")  # not an answer: a new request
    assert h.controller.current.mode is Mode.CLAUDE
    assert [text for text, _, _ in h.brain.sent][-1] == "Quelle heure est-il ?"


def test_unclear_command_is_confirmed_before_acting() -> None:
    h = Harness()
    assert said(h.run("Opus ?")) == ["Voulez-vous passer sur Opus 5.5 ?"]
    assert said(h.run("oui")) == ["Je passe sur Opus 5.5."]
    assert h.controller.current.model_lock == "opus"


# -- sessions ---------------------------------------------------------------------------


def test_create_resume_and_previous_sessions() -> None:
    h = Harness()
    h.run("Bonjour")  # Session 1 gets a Claude session id
    h.run("nouvelle session pour le projet boucherie", "Bonjour")
    assert h.controller.current.name == "boucherie"
    outputs = h.run("retourne sur la session précédente")
    assert said(outputs) == ["Je reprends la session Session 1, mode Claude, modèle automatique."]
    assert h.brain.calls[-1] == "resume:sid-1"
    h.run("reprends la session bouchrie")  # typo
    assert h.controller.current.name == "boucherie"


def test_ambiguous_session_name_asks_which_one() -> None:
    h = Harness()
    h.run("nouvelle session appelée Site restaurant", "nouvelle session appelée Site boucherie")
    outputs = h.run("reprends la session site")
    assert said(outputs) == ["J'ai trouvé Site restaurant et Site boucherie. Laquelle ?"]
    h.run("restaurant")
    assert h.controller.current.name == "Site restaurant"


def test_forget_needs_confirmation_and_moves_to_another_session() -> None:
    h = Harness()
    h.run("nouvelle session pour le projet boucherie")
    assert said(h.run("oublie cette session")) == [
        "Voulez-vous vraiment que j'oublie la session boucherie ?"
    ]
    outputs = h.run("oui")
    assert said(outputs)[0].startswith("J'ai oublié la session boucherie.")
    assert h.controller.current.name == "Session 1"
    assert [r.name for r in h.controller.sessions] == ["Session 1"]


def test_rename_and_duplicate_name() -> None:
    h = Harness()
    h.run("nouvelle session pour le projet boucherie")
    assert said(h.run("renomme cette session en Site restaurant")) == [
        "Cette session s'appelle maintenant Site restaurant."
    ]
    assert said(h.run("nouvelle session appelée site restaurant")) == [
        "Une session s'appelle déjà site restaurant. Voulez-vous la reprendre ?"
    ]


def test_list_sessions_is_spoken_and_shown() -> None:
    h = Harness([answer("Voici le menu de la semaine. Bon appétit.")])
    h.run("nouvelle session pour le projet boucherie", "Propose un menu")
    outputs = h.run("liste mes sessions")
    shown = [o for o in outputs if isinstance(o, ShowSessions)][0]
    assert [r.name for r in shown.sessions] == ["boucherie", "Session 1"]
    assert said(outputs) == [
        "Vous avez 2 sessions : boucherie, mode Claude, aujourd'hui : Voici le menu de la semaine "
        "et Session 1, mode Claude, aujourd'hui."
    ]


def test_restart_resumes_the_last_session_with_its_mode_and_model() -> None:
    sessions, usage = MemoryStore(), MemoryStore()
    first = Harness(sessions=sessions, usage=usage)
    first.run("nouvelle session pour le projet boucherie", "utilise Fable", "passe en mode code")
    first.run("Liste les fichiers")
    first.controller.close()

    second = Harness(sessions=sessions, usage=usage)
    assert said(second.started) == ["Session boucherie, mode Claude Code, Fable 5.1."]
    assert second.brain.calls == ["resume:sid-1"]
    assert second.brain.state.model == "fable"


# -- state, errors, control ---------------------------------------------------------------


def test_usage_count() -> None:
    h = Harness()
    h.run("Quelle heure est-il ?", "Corrige le bug.", "Qui est Ada Lovelace ?")
    assert said(h.run("combien de requêtes aujourd'hui ?")) == [
        "Aujourd'hui, 3 requêtes à Claude : 2 sur Haiku 4.5 et 1 sur Opus 5.5."
    ]


def test_quota_error_is_spoken_with_a_hint() -> None:
    h = Harness([answer(error=BrainError(BrainErrorKind.RATE_LIMIT))])
    outputs = h.run("Corrige le bug.")
    assert said(outputs)[0].startswith("J'ai atteint la limite de votre abonnement")
    assert "Haiku 4.5" in said(outputs)[0]


def test_repeat_and_open_web() -> None:
    h = Harness([answer("Il est midi.")])
    h.run("Quelle heure est-il ?")
    assert said(h.run("répète")) == ["Il est midi."]
    assert said(h.run("ouvre Claude dans le navigateur")) == [
        "J'ouvre Claude dans votre navigateur."
    ]
    assert h.opened == ["https://claude.ai"]


def test_abandoned_answer_is_interrupted_and_finished() -> None:
    h = Harness([answer("Un, ", "deux, ", "trois.")])
    outputs = h.controller.handle("Compte jusqu'à trois")
    next(outputs)
    outputs.close()  # e.g. the user closed the window mid-answer
    assert "interrupt" in h.brain.calls
    h.run("Et maintenant ?")  # the brain is free again
    assert len(h.brain.sent) == 2
