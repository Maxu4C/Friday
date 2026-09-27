from datetime import UTC, datetime

from friday.core.events import BrainError, BrainErrorKind, Mode
from friday.core.messages import error_message, mode_switched, model_switched
from friday.core.prompt import (
    MODE_CODE_MARKER,
    build_system_prompt,
    french_datetime,
    strip_mode_marker,
)

NOW = datetime(2026, 9, 27, 19, 5)


def test_french_datetime() -> None:
    assert french_datetime(NOW) == "dimanche 27 septembre 2026, 19 h 05"


def test_prompt_for_conversation_mode() -> None:
    prompt = build_system_prompt("Tu es FRIDAY.", Mode.CLAUDE, NOW, ("Mr", "Mr Chemmane"), "S1")
    assert prompt.startswith("Tu es FRIDAY.")
    assert "« Mr » ou « Mr Chemmane »" in prompt
    assert "Session : S1." in prompt
    assert "aucun outil" in prompt and MODE_CODE_MARKER in prompt


def test_prompt_for_code_mode() -> None:
    prompt = build_system_prompt("Tu es FRIDAY.", Mode.CLAUDE_CODE, NOW, ("Mr",), "S1")
    assert "Mode actuel : Claude Code" in prompt
    assert MODE_CODE_MARKER not in prompt


def test_strip_mode_marker() -> None:
    assert strip_mode_marker("Il faut le mode Claude Code. [MODE_CODE]") == (
        "Il faut le mode Claude Code.",
        True,
    )
    assert strip_mode_marker("Bonjour.") == ("Bonjour.", False)


def test_rate_limit_message_gives_reset_time_and_haiku_hint() -> None:
    reset = datetime(2026, 9, 27, 19, 0, tzinfo=UTC)
    text = error_message(
        BrainError(BrainErrorKind.RATE_LIMIT, resets_at=reset), "Opus 5.5", "Haiku 4.5"
    )
    assert text.startswith("J'ai atteint la limite de mon abonnement")
    assert "se réinitialise vers" in text
    assert "Haiku 4.5" in text


def test_rate_limit_message_on_simple_model_has_no_hint() -> None:
    text = error_message(BrainError(BrainErrorKind.RATE_LIMIT), "Haiku 4.5", "Haiku 4.5")
    assert "Tu peux aussi" not in text


def test_other_error_messages() -> None:
    assert "reconnecter" in error_message(BrainError(BrainErrorKind.AUTH), "Opus 5.5")
    assert error_message(BrainError(BrainErrorKind.MODEL_NOT_FOUND), "Opus 5.5") == (
        "Ce modèle n'est pas disponible, je reste sur Opus 5.5."
    )
    assert "réseau" in error_message(BrainError(BrainErrorKind.NETWORK), "Opus 5.5")
    assert error_message(BrainError(BrainErrorKind.INTERRUPTED), "x") == "D'accord, j'arrête."


def test_announcements() -> None:
    assert model_switched("Opus 5.5") == "Je passe sur Opus 5.5."
    assert mode_switched(Mode.CLAUDE_CODE) == "Je passe en mode Claude Code."
