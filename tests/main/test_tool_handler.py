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
    root = tmp_path / "fixture"
    path = _write_tools(
        root,
        {
            "check": {
                "argv": ["just", "check"],
                "description": "scoped check",
                "stages": "run_silent",
            }
        },
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    # The agent's own project is attribution only; the catalog repo names the
    # project the list is scoped to.
    monkeypatch.setenv("SASE_PROJECT", "host-project")
    monkeypatch.chdir(root)
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


def test_tool_list_json_reports_duration_class_and_null_calibration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(
        tmp_path,
        {
            "slow": {
                "argv": ["just", "check-full"],
                "description": "exhaustive check",
                "duration_class": "long",
            },
            "quick": {"argv": ["just", "check"]},
        },
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    clear_config_cache()

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=True))

    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    by_name = {tool["name"]: tool for tool in payload["tools"]}
    assert by_name["slow"]["duration_class"] == "long"
    assert by_name["slow"]["duration_calibration"] is None
    assert by_name["quick"]["duration_class"] == "short"
    assert by_name["quick"]["duration_calibration"] is None


def test_tool_list_human_shows_class_column(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(
        tmp_path,
        {"slow": {"argv": ["just", "check-full"], "duration_class": "long"}},
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    clear_config_cache()

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=False))

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "CLASS" in output
    assert "long" in output


def test_tool_list_calibration_mismatch_reaches_json_and_human_stderr(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = _write_tools(
        tmp_path,
        {"slow": {"argv": ["just", "check-full"], "duration_class": "long"}},
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    clear_config_cache()
    monkeypatch.setattr(
        "sase.main.tool_handler.tool_run_summary",
        lambda _request: {
            "last": None,
            "typical_duration_ms": 1000,
            "typical_sample_count": 20,
            "typical_status_breakdown": {},
            "diagnostics": [],
        },
    )

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=True))
    assert exit_info.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    calibration = payload["tools"][0]["duration_calibration"]
    assert payload["tools"][0]["duration_class"] == "long"
    assert calibration["suggested_class"] == "short"

    with pytest.raises(SystemExit) as exit_info:
        handle_tool_command(Namespace(tool_subcommand="list", json=False))
    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    assert "slow:" in captured.err
    assert "suggest short" in captured.err


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
