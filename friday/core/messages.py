"""Short French sentences FRIDAY says about her own state."""

from __future__ import annotations

from datetime import datetime

from friday.core.events import BrainError, BrainErrorKind, Mode

MODE_LABELS = {Mode.CLAUDE: "Claude", Mode.CLAUDE_CODE: "Claude Code"}


def _clock(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.hour} h {local.minute:02d}"


def error_message(
    error: BrainError, current_model_label: str, simple_model_label: str | None = None
) -> str:
    kind = error.kind
    if kind is BrainErrorKind.RATE_LIMIT:
        text = "J'ai atteint la limite de mon abonnement, réessaie plus tard."
        if error.resets_at is not None:
            text += f" Elle se réinitialise vers {_clock(error.resets_at)}."
        if simple_model_label and simple_model_label != current_model_label:
            text += f" Tu peux aussi essayer de passer sur {simple_model_label}."
        return text
    if kind is BrainErrorKind.AUTH:
        return "Ma connexion à Claude a expiré. Lance claude dans un terminal pour te reconnecter."
    if kind is BrainErrorKind.MODEL_NOT_FOUND:
        return f"Ce modèle n'est pas disponible, je reste sur {current_model_label}."
    if kind is BrainErrorKind.NETWORK:
        return "Je n'ai pas de connexion réseau. Vérifie ta connexion internet."
    if kind is BrainErrorKind.INTERRUPTED:
        return "D'accord, j'arrête."
    if kind is BrainErrorKind.TIMEOUT:
        return "Claude met trop de temps à répondre, j'ai abandonné cette demande."
    if kind is BrainErrorKind.PROCESS_DIED:
        return "Claude Code s'est arrêté. Je le relance à la prochaine demande."
    detail = f" ({error.message})" if error.message else ""
    return f"Une erreur est survenue{detail}."


def model_switched(label: str) -> str:
    return f"Je passe sur {label}."


def mode_switched(mode: Mode) -> str:
    return f"Je passe en mode {MODE_LABELS[mode]}."
