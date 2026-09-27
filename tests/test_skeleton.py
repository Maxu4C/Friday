from pathlib import Path
from typing import Any

import pytest
import yaml

from friday.__main__ import main
from friday.config import ConfigError, load_config, parse_config
from friday.core.events import Mode

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "friday.example.yaml"


def test_example_config_is_safe_and_consistent() -> None:
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))

    assert config["ui"]["host"] == "127.0.0.1"
    assert config["claude"]["default_mode"] in {"claude", "claude_code"}
    available = config["models"]["available"]
    assert config["models"]["simple"] in available
    assert config["models"]["complex"] in available


def test_example_config_loads() -> None:
    config = load_config(EXAMPLE_CONFIG)
    assert config.claude.default_mode is Mode.CLAUDE
    assert config.models.complex == "opus" and config.models.label("opus") == "Opus 5.5"
    assert config.claude.persona_file.exists()
    assert config.ui_port == 8765
    assert "PowerShell(Remove-Item *)" in config.claude.confirm_tools
    assert "Bash(rm *)" in config.claude.confirm_tools


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    return raw


def test_config_refuses_network_exposure() -> None:
    raw = _raw()
    raw["ui"]["host"] = "0.0.0.0"
    with pytest.raises(ConfigError, match="127.0.0.1"):
        parse_config(raw)


def test_config_refuses_unknown_default_model() -> None:
    raw = _raw()
    raw["models"]["complex"] = "gpt"
    with pytest.raises(ConfigError, match="models.complex"):
        parse_config(raw)


def test_config_refuses_unknown_mode() -> None:
    raw = _raw()
    raw["claude"]["default_mode"] = "turbo"
    with pytest.raises(ConfigError, match="default_mode"):
        parse_config(raw)


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
