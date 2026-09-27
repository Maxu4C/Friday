"""Short French sentences FRIDAY says about her own state (she addresses the user as "vous")."""

from __future__ import annotations

from datetime import date, datetime

from friday.core.events import BrainError, BrainErrorKind, Mode

MODE_LABELS = {Mode.CLAUDE: "Claude", Mode.CLAUDE_CODE: "Claude Code"}
_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)  # fmt: skip


def _clock(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.hour} h {local.minute:02d}"


def error_message(
    error: BrainError, current_model_label: str, simple_model_label: str | None = None
) -> str:
    kind = error.kind
    if kind is BrainErrorKind.RATE_LIMIT:
        text = "J'ai atteint la limite de votre abonnement, réessayez plus tard."
        if error.resets_at is not None:
            text += f" Elle se réinitialise vers {_clock(error.resets_at)}."
        if simple_model_label and simple_model_label != current_model_label:
            text += f" Vous pouvez aussi essayer de passer sur {simple_model_label}."
        return text
    if kind is BrainErrorKind.AUTH:
        return (
            "Ma connexion à Claude a expiré. Lancez claude dans un terminal pour vous reconnecter."
        )
    if kind is BrainErrorKind.MODEL_NOT_FOUND:
        return f"Ce modèle n'est pas disponible, je reste sur {current_model_label}."
    if kind is BrainErrorKind.NETWORK:
        return "Je n'ai pas de connexion réseau. Vérifiez votre connexion internet."
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


def relative_day(day: date, today: date) -> str:
    delta = (today - day).days
    if delta == 0:
        return "aujourd'hui"
    if delta == 1:
        return "hier"
    if 1 < delta < 7:
        return f"il y a {delta} jours"
    text = f"le {day.day} {_MONTHS[day.month - 1]}"
    return text if day.year == today.year else f"{text} {day.year}"


def enumerate_fr(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " et " + items[-1]
