"""Tests for bead CLI workspace resolution behavior."""

from pathlib import Path
from unittest.mock import patch

from sase.bead.cli import _find_beads_location


def test_find_beads_location_non_vc_prefers_primary_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase" / "sdd" / "beads").mkdir(parents=True)
    monkeypatch.chdir(workspace_2)

    with patch("sase.bead.workspace.resolve_primary_workspace", return_value=primary):
        root, beads_dirname = _find_beads_location()

    assert root == primary / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_find_beads_location_non_vc_walkup_fallback_when_primary_unknown(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "project_2"
    (workspace / ".sase" / "sdd" / "beads").mkdir(parents=True)
    monkeypatch.chdir(workspace)

    with patch("sase.bead.workspace.resolve_primary_workspace", return_value=None):
        root, beads_dirname = _find_beads_location()

    assert root == workspace / ".sase" / "sdd"
    assert beads_dirname == "beads"


def test_find_beads_location_non_vc_variant_workspace_maps_to_primary(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)

    primary = tmp_path / "workspaces" / "yserve_yp_last_conv" / "google3"
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.gp").write_text(f"WORKSPACE_DIR: {primary}\n")
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)

    variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    variant.mkdir(parents=True)
    monkeypatch.chdir(variant)

    with patch("sase.sdd.get_sdd_config", return_value=None):
        root, beads_dirname = _find_beads_location()

    assert root == primary / ".sase" / "sdd"
    assert beads_dirname == "beads"
