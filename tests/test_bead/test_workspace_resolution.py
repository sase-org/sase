"""Tests for workspace-aware beads directory resolution."""

from pathlib import Path

from sase.bead.workspace import _enumerate_workspace_beads_dirs


def test_enumerate_workspace_beads_dirs_non_vc_primary_only(tmp_path: Path) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase" / "sdd" / "beads").mkdir(parents=True)

    result = _enumerate_workspace_beads_dirs(primary)

    assert result == [primary / ".sase" / "sdd" / "beads"]


def test_enumerate_workspace_beads_dirs_vc_includes_workspaces(tmp_path: Path) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase_beads").mkdir(parents=True)
    (workspace_2 / ".sase_beads").mkdir(parents=True)

    result = _enumerate_workspace_beads_dirs(primary)

    assert result == [primary / ".sase_beads", workspace_2 / ".sase_beads"]
