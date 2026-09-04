"""Startup grouping restoration for the ACE TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.app import AceApp
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.patch_groups import PatchGroupingMode


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


def test_startup_restores_patch_grouping_mode_file(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    (sase_dir / "patch_grouping_mode.txt").write_text(PatchGroupingMode.BY_STATUS.value)
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False)

    assert app._patch_grouping_mode is PatchGroupingMode.BY_STATUS
    assert (
        app._patch_group_fold_registry
        is app._patch_group_fold_registries[PatchGroupingMode.BY_STATUS]
    )
    assert set(app._patch_group_fold_registries) == {PatchGroupingMode.BY_STATUS}


def test_startup_stores_sanity_refresh_interval(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False, sanity_refresh_interval=120)

    assert app.sanity_refresh_interval == 120
    assert app.refresh_interval == 10


def test_startup_uses_defaults_for_invalid_grouping_mode_files(
    tmp_path: Path, monkeypatch: Any
) -> None:
    sase_dir = tmp_path / ".sase"
    sase_dir.mkdir()
    (sase_dir / "grouping_mode.txt").write_text("nope\n")
    (sase_dir / "patch_grouping_mode.txt").write_text("also-nope\n")
    monkeypatch.setenv("HOME", str(tmp_path))

    app = AceApp(auto_start_axe=False)

    assert app._grouping_mode is GroupingMode.STANDARD
    assert app._group_fold_registry is app._group_fold_registries[GroupingMode.STANDARD]
    assert app._patch_grouping_mode is PatchGroupingMode.BY_PROJECT
    assert (
        app._patch_group_fold_registry
        is app._patch_group_fold_registries[PatchGroupingMode.BY_PROJECT]
    )
