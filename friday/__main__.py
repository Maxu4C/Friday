"""FRIDAY command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from friday.adapters.brain_claude_code import ClaudeCodeBrain
    from friday.config import FridayConfig
    from friday.core.controller import Controller

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging(config: FridayConfig) -> None:
    from friday.config import PROJECT_ROOT

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    def handler(name: str) -> RotatingFileHandler:
        rotating = RotatingFileHandler(
            log_dir / name, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        rotating.setFormatter(logging.Formatter(LOG_FORMAT))
        return rotating

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler("friday.log"))
    actions = logging.getLogger("friday.actions")
    actions.addHandler(handler("actions.log"))
    actions.propagate = False


def create_brain(config: FridayConfig) -> ClaudeCodeBrain:
    """Composition root: wire the Claude Code adapter from the configuration."""
    from friday.adapters.brain_claude_code import BrainSettings, ClaudeCodeBrain
    from friday.core.ports import SessionState

    claude = config.claude
    settings = BrainSettings(
        binary=claude.binary,
        workspace=claude.workspace,
        runtime_dir=config.data_dir / "runtime",
        persona=claude.persona_file.read_text(encoding="utf-8"),
        user_names=config.user_names,
        code_tools=claude.code_tools,
        allowed_tools=claude.allowed_tools,
        confirm_tools=claude.confirm_tools,
        request_timeout=claude.request_timeout_seconds,
    )
    # Placeholder until Controller.start() loads the last active session.
    state = SessionState(mode=claude.default_mode, model=config.models.complex, name="Session 1")
    return ClaudeCodeBrain(settings, state)


def create_controller(config: FridayConfig) -> Controller:
    from friday.adapters.json_store import JsonFile
    from friday.core.controller import Controller, ControllerSettings
    from friday.core.intents import IntentParser
    from friday.core.router import Router

    models = config.models
    parser = IntentParser({alias: info.spoken for alias, info in models.available.items()})
    settings = ControllerSettings(
        model_labels={alias: info.label for alias, info in models.available.items()},
        simple_model=models.simple,
        complex_model=models.complex,
        default_mode=config.claude.default_mode,
        workspace=config.claude.workspace,
    )
    return Controller(
        create_brain(config),
        parser,
        Router(config.router),
        settings,
        JsonFile(config.data_dir / "sessions.json"),
        JsonFile(config.data_dir / "usage.json"),
    )


def _chat() -> int:
    from friday.chat import ChatSession
    from friday.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Configuration invalide : {exc}", file=sys.stderr)
        return 2
    _setup_logging(config)
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    session = ChatSession(create_controller(config), write=write, read=input)
    return session.run()


def _list_devices() -> int:
    from friday.adapters.audio_io import Kind, default_device_name, device_names, query_devices

    devices = query_devices()
    sections: tuple[tuple[Kind, str, str], ...] = (
        ("input", "Micros", "input_device"),
        ("output", "Sorties", "output_device"),
    )
    for kind, title, key in sections:
        default = default_device_name(devices, kind)
        print(f"{title} (audio.{key}) :")
        for name in device_names(devices, kind):
            mark = "   <- défaut Windows" if name == default else ""
            print(f'  "{name}"{mark}')
        print()
    print("Copie un nom entre guillemets dans config\\friday.yaml (null = défaut Windows).")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(prog="friday", description="FRIDAY, assistant vocal local")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("devices", help="liste les périphériques audio")
    commands.add_parser("chat", help="discute avec FRIDAY au clavier")

    args = parser.parse_args(argv)
    if args.command == "devices":
        return _list_devices()
    if args.command == "chat":
        return _chat()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
