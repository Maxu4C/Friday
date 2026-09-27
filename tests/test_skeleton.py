from pathlib import Path

import pytest
import yaml

from friday.__main__ import main

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "friday.example.yaml"


def test_example_config_is_safe_and_consistent() -> None:
    config = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))

    assert config["ui"]["host"] == "127.0.0.1"
    assert config["claude"]["default_mode"] in {"claude", "claude_code"}
    available = config["models"]["available"]
    assert config["models"]["simple"] in available
    assert config["models"]["complex"] in available


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main([])
    assert exit_info.value.code == 2
