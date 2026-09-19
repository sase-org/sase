from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.tool.argv import (
    ToolRunUsageError,
    _parse_run_words,
    _redact_display_argv,
    resolve_run_argv,
)


def test_parse_run_words_adhoc_and_named() -> None:
    adhoc, name, payload = _parse_run_words(["--", "printf", "out"])
    assert adhoc is True
    assert name is None
    assert payload == ("printf", "out")

    adhoc, name, payload = _parse_run_words(["check", "--", "-k"])
    assert adhoc is False
    assert name == "check"
    assert payload == ("-k",)


def test_redact_display_argv_masks_secret_payloads() -> None:
    display = _redact_display_argv(
        ["sh", "-c", "echo token=sekrit", "--password", "hunter2", "--token=abc"]
    )
    assert display[2] == "echo token=<redacted>"
    assert display[3] == "--password"
    assert display[4] == "<redacted>"
    assert display[5] == "--token=<redacted>"


def test_resolve_named_tool_rejects_denied_extra_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "sase"
    config_dir.mkdir()
    (config_dir / "sase.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["just", "check"], "args": "deny"}}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    clear_config_cache()
    with pytest.raises(ToolRunUsageError, match="does not allow extra arguments"):
        resolve_run_argv(["check", "nope"])
