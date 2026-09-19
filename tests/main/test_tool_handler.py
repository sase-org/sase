"""Handler tests for ``sase tool list``."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.main.tool_handler import handle_tool_command


def _write_tools(root: Path, tools: dict[object, object]) -> Path:
    config_dir = root / "sase"
    config_dir.mkdir(parents=True)
    path = config_dir / "sase.yml"
    path.write_text(yaml.dump({"tools": tools}), encoding="utf-8")
    return path


def test_tool_list_json_is_versioned_with_empty_last_typical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(
        tmp_path,
        {
            "check": {
                "argv": ["just", "check"],
                "description": "scoped check",
                "stages": "run_silent",
            }
        },
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SASE_PROJECT", "fixture")
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    clear_config_cache()

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=True))

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["project"] == "fixture"
    assert [tool["name"] for tool in payload["tools"]] == ["check"]
    tool = payload["tools"][0]
    assert tool["argv"] == ["just", "check"]
    assert tool["last"] is None
    assert tool["typical_duration_ms"] is None
    assert tool["typical_sample_count"] == 0
    assert "digest" in tool


def test_tool_list_human_uses_em_dash_for_empty_samples(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(tmp_path, {"check": {"argv": ["just", "check"]}})
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    clear_config_cache()

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=False))

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "check" in output
    assert "—" in output


def test_malformed_catalog_exits_2_without_listing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(tmp_path, {"check": {"argv": ["just", "check"], "shell": True}})
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=True))

    assert exit_info.value.code == 2
    captured = capsys.readouterr()
    assert "tools.check" in captured.err
    assert "schema_version" not in captured.out
