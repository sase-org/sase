"""Project-layer tool catalog loading and operational tool_runs policy."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache, load_merged_config
from sase.config.tools import (
    ToolCatalogError,
    ToolRunsConfigError,
    get_tool_runs_config,
    load_project_tool_catalog,
)


def _write_project_tools(root: Path, tools: dict[object, object]) -> Path:
    config_dir = root / "sase"
    config_dir.mkdir(parents=True)
    path = config_dir / "sase.yml"
    path.write_text(yaml.dump({"tools": tools}), encoding="utf-8")
    return path


def test_sase_project_catalog_has_five_named_tools() -> None:
    catalog = load_project_tool_catalog()
    names = [entry.name for entry in catalog.entries]
    assert names == ["check", "check-full", "install", "test", "test-visual"]
    by_name = {entry.name: entry for entry in catalog.entries}
    assert by_name["check"].definition["argv"] == ["just", "check"]
    assert by_name["check"].definition["stages"] == "run_silent"
    assert by_name["check"].definition["args"] == "deny"
    assert by_name["check-full"].definition["argv"] == ["just", "check-full"]
    assert by_name["install"].definition["stages"] == "none"
    assert by_name["test"].definition["args"] == "allow"
    assert by_name["test-visual"].definition["argv"] == ["just", "test-visual"]
    assert all(entry.digest for entry in catalog.entries)


def test_missing_catalog_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: None)
    catalog = load_project_tool_catalog()
    assert catalog.entries == ()
    assert catalog.path is None


def test_malformed_project_yaml_is_actionable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "sase.yml"
    path.write_text("tools: [not, a, mapping\n", encoding="utf-8")
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match="sase.yml"):
        load_project_tool_catalog()


def test_unknown_tool_field_names_the_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _write_project_tools(
        tmp_path,
        {"check": {"argv": ["just", "check"], "shell": True}},
    )
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match=r"tools\.check"):
        load_project_tool_catalog()


def test_empty_argv_names_the_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = _write_project_tools(tmp_path, {"check": {"argv": []}})
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    with pytest.raises(ToolCatalogError, match=r"tools\.check"):
        load_project_tool_catalog()


def test_non_project_tools_do_not_change_execution_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user_dir = tmp_path / "cfg"
    user_dir.mkdir()
    (user_dir / "sase.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "user"]}}}),
        encoding="utf-8",
    )
    (user_dir / "sase_machine.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "overlay"]}}}),
        encoding="utf-8",
    )
    path = _write_project_tools(
        tmp_path / "proj",
        {"check": {"argv": ["just", "check"], "description": "project"}},
    )
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", user_dir)
    monkeypatch.setattr("sase.config.core.get_local_config_path", lambda: path)
    monkeypatch.setattr("sase.config.tools.get_local_config_path", lambda: path)
    monkeypatch.setattr(
        "sase.config.core.selected_overlay_paths",
        lambda: [user_dir / "sase_machine.yml"],
    )
    clear_config_cache()
    merged = load_merged_config()
    assert merged["tools"]["check"]["argv"] == ["just", "check"]
    catalog = load_project_tool_catalog()
    assert [entry.name for entry in catalog.entries] == ["check"]
    assert catalog.entries[0].definition["argv"] == ["just", "check"]
    assert any("ignoring tools" in item for item in catalog.diagnostics)


def test_user_tools_without_project_catalog_do_not_appear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    user_dir = tmp_path / "cfg"
    user_dir.mkdir()
    (user_dir / "sase.yml").write_text(
        yaml.dump({"tools": {"check": {"argv": ["echo", "user"]}}}),
        encoding="utf-8",
    )
    project_config = tmp_path / "proj" / "sase" / "sase.yml"
    project_config.parent.mkdir(parents=True)
    project_config.write_text("is_sase_managed: false\n", encoding="utf-8")
    monkeypatch.setattr("sase.config.core.CONFIG_DIR", user_dir)
    monkeypatch.setattr(
        "sase.config.core.get_local_config_path", lambda: project_config
    )
    monkeypatch.setattr(
        "sase.config.tools.get_local_config_path", lambda: project_config
    )
    clear_config_cache()
    merged = load_merged_config()
    assert "tools" not in merged or merged["tools"] in ({}, None)
    catalog = load_project_tool_catalog()
    assert catalog.entries == ()


def test_deep_merge_would_splice_tool_argv_lists() -> None:
    """Document why tools must not ride the ordinary recursive merge."""
    from sase.config.core import _deep_merge

    spliced = _deep_merge(
        {"tools": {"check": {"argv": ["echo", "user"]}}},
        {"tools": {"check": {"argv": ["just", "check"]}}},
    )
    assert spliced["tools"]["check"]["argv"] == ["echo", "user", "just", "check"]


def test_tool_runs_defaults_are_positive_and_consistent() -> None:
    policy = get_tool_runs_config()
    assert policy["summary_days"] == 180
    assert policy["detail_days"] == 60
    assert policy["log_days"] == 14
    assert policy["detail_days"] <= policy["summary_days"]
    assert policy["log_days"] <= policy["detail_days"]
    assert policy["log_max_bytes"] == 2147483648
    assert policy["run_log_max_bytes"] == 268435456
    assert policy["event_max_bytes"] == 16777216


def test_tool_runs_rejects_inconsistent_horizons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.core.load_merged_config",
        lambda: {"tool_runs": {"summary_days": 10, "detail_days": 20, "log_days": 1}},
    )
    with pytest.raises(ToolRunsConfigError, match="detail_days"):
        get_tool_runs_config()
