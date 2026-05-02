"""Tests for workspace-aware beads directory resolution."""

from pathlib import Path
from unittest.mock import patch

from sase.bead.project_name import _cwd_matches_project_workspace
from sase.bead.workspace import (
    _enumerate_workspace_beads_dirs,
    _resolve_by_scanning_projects,
    resolve_primary_workspace,
)


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
    (primary / "sdd/beads").mkdir(parents=True)
    (workspace_2 / "sdd/beads").mkdir(parents=True)

    result = _enumerate_workspace_beads_dirs(primary)

    assert result == [primary / "sdd/beads", workspace_2 / "sdd/beads"]


# --- cwd_matches_workspace_variant tests ---


def test_numbered_workspace_basic_match() -> None:
    primary = Path("/a/b/yserve/google3")
    assert _cwd_matches_project_workspace("/a/b/yserve_101/google3", primary, "yserve")


def test_numbered_workspace_cwd_deeper_than_primary() -> None:
    primary = Path("/a/b/yserve/google3")
    assert _cwd_matches_project_workspace(
        "/a/b/yserve_101/google3/deep/path", primary, "yserve"
    )


def test_numbered_workspace_no_match_different_project() -> None:
    primary = Path("/a/b/yserve/google3")
    assert not _cwd_matches_project_workspace(
        "/a/b/other_101/google3", primary, "yserve"
    )


def test_exact_match_same_dir() -> None:
    primary = Path("/a/b/yserve/google3")
    assert _cwd_matches_project_workspace("/a/b/yserve/google3", primary, "yserve")


def test_numbered_workspace_no_match_cwd_too_short() -> None:
    primary = Path("/a/b/yserve/google3")
    assert not _cwd_matches_project_workspace("/a/b", primary, "yserve")


def test_numbered_workspace_suffix_only_digits() -> None:
    primary = Path("/a/b/yserve/google3")
    assert _cwd_matches_project_workspace("/a/b/yserve_abc/google3", primary, "yserve")


def test_numbered_workspace_variant_to_variant_match() -> None:
    primary = Path("/a/b/yserve_yp_last_conv/google3")
    assert _cwd_matches_project_workspace("/a/b/yserve_101/google3", primary, "yserve")


# --- _resolve_by_scanning_projects tests ---


def test_scanning_projects_direct_match(tmp_path: Path, monkeypatch) -> None:
    """CWD is directly under the primary workspace."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "myproj"
    projects_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "myproj"
    primary.mkdir(parents=True)
    (projects_dir / "myproj.gp").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = _resolve_by_scanning_projects(str(primary / "subdir"))
    assert result == primary


def test_scanning_projects_numbered_variant(tmp_path: Path, monkeypatch) -> None:
    """CWD is under a numbered workspace variant."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "myproj"
    projects_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "myproj" / "src"
    primary.mkdir(parents=True)
    (projects_dir / "myproj.gp").write_text(f"WORKSPACE_DIR: {primary}\n")

    # Simulate numbered workspace: myproj_42/src
    numbered = tmp_path / "workspaces" / "myproj_42" / "src"
    numbered.mkdir(parents=True)

    result = _resolve_by_scanning_projects(str(numbered))
    assert result == primary


def test_scanning_projects_variant_to_variant(tmp_path: Path, monkeypatch) -> None:
    """CWD under one variant should match a primary path under another variant."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "yserve"
    projects_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "yserve_yp_last_conv" / "google3"
    primary.mkdir(parents=True)
    (projects_dir / "yserve.gp").write_text(f"WORKSPACE_DIR: {primary}\n")

    cwd_variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    cwd_variant.mkdir(parents=True)

    result = _resolve_by_scanning_projects(str(cwd_variant))
    assert result == primary


def test_scanning_projects_primary_not_on_disk(tmp_path: Path, monkeypatch) -> None:
    """Project name should resolve even when primary workspace doesn't exist on disk."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "yserve"
    projects_dir.mkdir(parents=True)
    # Primary workspace path in .gp file — does NOT exist on disk.
    primary = tmp_path / "workspaces" / "yserve" / "google3"
    (projects_dir / "yserve.gp").write_text(f"WORKSPACE_DIR: {primary}\n")

    # CWD is under a variant workspace that DOES exist.
    variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    variant.mkdir(parents=True)

    # _resolve_by_scanning_projects returns None (primary isn't on disk),
    # but scan_projects_for_cwd still matches the project name.
    result = _resolve_by_scanning_projects(str(variant))
    assert result is None

    from sase.bead.project_name import scan_projects_for_cwd

    scanned = scan_projects_for_cwd(str(variant))
    assert scanned is not None
    assert scanned[0] == "yserve"


def test_scanning_projects_no_match(tmp_path: Path, monkeypatch) -> None:
    """CWD doesn't match any project."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "myproj"
    projects_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "myproj"
    primary.mkdir(parents=True)
    (projects_dir / "myproj.gp").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = _resolve_by_scanning_projects("/some/other/path")
    assert result is None


def test_resolve_primary_workspace_via_provider_when_workspace_dir_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Falls back to workspace provider when .gp lacks WORKSPACE_DIR."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.gp").write_text("RUNNING:\nNAME: x\n")

    primary = tmp_path / "workspaces" / project_name / "google3"
    primary.mkdir(parents=True)
    monkeypatch.chdir(primary)

    with (
        patch("sase.workspace_provider.get_workspace_name", return_value=project_name),
        patch(
            "sase.workspace_provider.detect_workflow_type", return_value="hg"
        ) as mock_detect,
        patch(
            "sase.workspace_provider.get_workspace_directory",
            return_value=str(primary),
        ) as mock_get_dir,
    ):
        result = resolve_primary_workspace()

    assert result == primary
    mock_detect.assert_called_once_with(str(project_dir / f"{project_name}.gp"))
    mock_get_dir.assert_called_once_with("hg", 1, project_name, "")
