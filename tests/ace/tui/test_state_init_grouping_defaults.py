"""Startup grouping restoration for the ACE TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode


def test_startup_restores_agent_grouping_mode_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    (sase_dir / "grouping_mode.txt").write_text(GroupingMode.BY_STATUS.value)
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False)

    assert app._grouping_mode is GroupingMode.BY_STATUS
    assert (
        app._group_fold_registry is app._group_fold_registries[GroupingMode.BY_STATUS]
    )
    assert set(app._group_fold_registries) == {GroupingMode.BY_STATUS}


def test_startup_restores_changespec_grouping_mode_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    (sase_dir / "changespec_grouping_mode.txt").write_text(
        ChangeSpecGroupingMode.BY_STATUS.value
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False)

    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_STATUS
    assert (
        app._changespec_group_fold_registry
        is app._changespec_group_fold_registries[ChangeSpecGroupingMode.BY_STATUS]
    )
    assert set(app._changespec_group_fold_registries) == {
        ChangeSpecGroupingMode.BY_STATUS
    }


def test_startup_uses_defaults_for_invalid_grouping_mode_files(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    (sase_dir / "grouping_mode.txt").write_text("nope\n")
    (sase_dir / "changespec_grouping_mode.txt").write_text("also-nope\n")
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False)

    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._group_fold_registry is app._group_fold_registries[GroupingMode.STANDARD]
    assert app._changespec_grouping_mode is ChangeSpecGroupingMode.BY_PROJECT
    assert (
        app._changespec_group_fold_registry
        is app._changespec_group_fold_registries[ChangeSpecGroupingMode.BY_PROJECT]
    )
