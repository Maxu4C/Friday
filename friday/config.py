"""Load and validate config/friday.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from friday.core.events import Mode
from friday.core.router import RouterRules

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "friday.yaml"
EXAMPLE_CONFIG = PROJECT_ROOT / "config" / "friday.example.yaml"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelInfo:
    alias: str
    label: str
    spoken: tuple[str, ...]


@dataclass(frozen=True)
class ModelsConfig:
    simple: str
    complex: str
    available: dict[str, ModelInfo]

    def label(self, alias: str) -> str:
        info = self.available.get(alias)
        return info.label if info else alias


@dataclass(frozen=True)
class ClaudeConfig:
    binary: str
    default_mode: Mode
    workspace: Path
    persona_file: Path
    request_timeout_seconds: float
    permission_timeout_seconds: float
    code_tools: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    confirm_tools: tuple[str, ...]


@dataclass(frozen=True)
class TtsConfig:
    enabled: bool
    engine: str  # "piper" or "windows_sapi"
    voice: str
    models_dir: Path
    length_scale: float
    noise_scale: float
    noise_w_scale: float
    volume: float
    softness: float
    speaker: str | int | None


@dataclass(frozen=True)
class AudioConfig:
    input_device: str | None
    output_device: str | None


@dataclass(frozen=True)
class FridayConfig:
    user_names: tuple[str, ...]
    claude: ClaudeConfig
    models: ModelsConfig
    router: RouterRules
    tts: TtsConfig
    audio: AudioConfig
    ui_host: str
    ui_port: int
    data_dir: Path
    raw: dict[str, Any]


def load_config(path: Path | None = None) -> FridayConfig:
    path = path or (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Fichier de configuration introuvable : {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} n'est pas un YAML valide : {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} doit contenir un dictionnaire YAML.")
    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> FridayConfig:
    models = _parse_models(_section(raw, "models"))
    claude = _parse_claude(_section(raw, "claude"))
    ui = _section(raw, "ui")
    host = _str(ui, "ui.host")
    if host != "127.0.0.1":
        raise ConfigError(
            "ui.host doit rester 127.0.0.1 : FRIDAY ne doit pas être exposée sur le réseau."
        )
    port = ui.get("port")
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ConfigError("ui.port doit être un entier entre 1024 et 65535.")
    names = _section(raw, "user").get("names")
    if not isinstance(names, list) or not names or not all(isinstance(n, str) for n in names):
        raise ConfigError("user.names doit être une liste non vide de textes.")
    data_dir = _path(raw.get("data_dir", "data"), "data_dir")
    return FridayConfig(
        user_names=tuple(names),
        claude=claude,
        models=models,
        router=_parse_router(_section(raw, "router")),
        tts=_parse_tts(_section(raw, "tts")),
        audio=_parse_audio(_section(raw, "audio")),
        ui_host=host,
        ui_port=port,
        data_dir=data_dir,
        raw=raw,
    )


def _parse_models(section: dict[str, Any]) -> ModelsConfig:
    available_raw = section.get("available")
    if not isinstance(available_raw, dict) or not available_raw:
        raise ConfigError("models.available doit lister au moins un modèle.")
    available: dict[str, ModelInfo] = {}
    for alias, info in available_raw.items():
        if not isinstance(info, dict):
            raise ConfigError(f"models.available.{alias} doit être un dictionnaire.")
        spoken = info.get("aliases") or [alias]
        available[str(alias)] = ModelInfo(
            alias=str(alias),
            label=str(info.get("label", alias)),
            spoken=tuple(str(s) for s in spoken),
        )
    simple, complex_ = _str(section, "models.simple"), _str(section, "models.complex")
    for key, alias in (("models.simple", simple), ("models.complex", complex_)):
        if alias not in available:
            raise ConfigError(f"{key} = {alias!r} n'est pas dans models.available.")
    return ModelsConfig(simple=simple, complex=complex_, available=available)


def _parse_claude(section: dict[str, Any]) -> ClaudeConfig:
    mode = _str(section, "claude.default_mode")
    if mode not in {m.value for m in Mode}:
        raise ConfigError("claude.default_mode doit valoir 'claude' ou 'claude_code'.")
    return ClaudeConfig(
        binary=_str(section, "claude.binary"),
        default_mode=Mode(mode),
        workspace=_path(section.get("workspace"), "claude.workspace"),
        persona_file=_path(section.get("persona_file", "config/persona.md"), "claude.persona_file"),
        request_timeout_seconds=_positive(section, "request_timeout_seconds", 180),
        permission_timeout_seconds=_positive(section, "permission_timeout_seconds", 30),
        code_tools=_str_list(section, "code_tools"),
        allowed_tools=_str_list(section, "allowed_tools"),
        confirm_tools=_str_list(section, "confirm_tools"),
    )


def _parse_router(section: dict[str, Any]) -> RouterRules:
    max_words = section.get("simple_max_words", 20)
    if not isinstance(max_words, int) or max_words < 1:
        raise ConfigError("router.simple_max_words doit être un entier positif.")
    lists = {}
    for key in ("simple_patterns", "complex_patterns"):
        value = section.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"router.{key} doit être une liste de textes.")
        lists[key] = tuple(value)
    return RouterRules(max_words, lists["simple_patterns"], lists["complex_patterns"])


TTS_ENGINES = ("piper", "windows_sapi")


def _parse_tts(section: dict[str, Any]) -> TtsConfig:
    engine = section.get("engine", "piper")
    if engine not in TTS_ENGINES:
        raise ConfigError(f"tts.engine doit valoir {' ou '.join(TTS_ENGINES)}.")
    speaker = section.get("speaker")
    if speaker is not None and not isinstance(speaker, str | int):
        raise ConfigError("tts.speaker doit être un nom, un numéro ou null.")
    return TtsConfig(
        enabled=bool(section.get("enabled", True)),
        engine=engine,
        voice=_str(section, "tts.voice"),
        models_dir=_path(section.get("models_dir", "models/piper"), "tts.models_dir"),
        length_scale=_bounded(section, "length_scale", 1.0, 0.3, 3),
        noise_scale=_bounded(section, "noise_scale", 0.667, 0, 2),
        noise_w_scale=_bounded(section, "noise_w_scale", 0.8, 0, 2),
        volume=_bounded(section, "volume", 1.0, 0.05, 2),
        softness=_bounded(section, "softness", 0.0, 0, 1),
        speaker=speaker,
    )


def _bounded(section: dict[str, Any], key: str, default: float, low: float, high: float) -> float:
    value = section.get(key, default)
    if not isinstance(value, int | float) or not low <= value <= high:
        raise ConfigError(f"tts.{key} doit être un nombre entre {low} et {high}.")
    return float(value)


def _parse_audio(section: dict[str, Any]) -> AudioConfig:
    devices = {}
    for key in ("input_device", "output_device"):
        value = section.get(key)
        if value is not None and not isinstance(value, str):
            raise ConfigError(
                f"audio.{key} doit être un nom de périphérique entre guillemets, ou null."
            )
        devices[key] = value
    return AudioConfig(devices["input_device"], devices["output_device"])


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"La section '{key}' est absente ou invalide.")
    return value


def _str(section: dict[str, Any], key: str) -> str:
    value = section.get(key.rsplit(".", 1)[-1])
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} doit être un texte non vide.")
    return value


def _str_list(section: dict[str, Any], key: str) -> tuple[str, ...]:
    value = section.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"claude.{key} doit être une liste de textes.")
    return tuple(value)


def _positive(section: dict[str, Any], key: str, default: float) -> float:
    value = section.get(key, default)
    if not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"claude.{key} doit être un nombre positif.")
    return float(value)


def _path(value: Any, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} doit être un chemin.")
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path
