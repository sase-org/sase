"""Tests for workspace-aware beads directory resolution."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.bead.project_name import (
    _cwd_matches_project_workspace,
    infer_project_name_from_cwd,
)
from sase.bead.workspace import (
    _canonical_project_beads_dir,
    _current_or_primary_beads_dir,
    get_all_project_beads_dirs,
    get_project_beads_dirs,
    get_project_beads_dirs_for_project,
    _resolve_by_scanning_projects,
    resolve_primary_workspace,
)
from tests.sdd_policy_helpers import set_sdd_policy


def _set_sdd_config(monkeypatch, *, storage: str = "auto") -> None:
    if storage == "auto":
        storage = "local"
    set_sdd_policy(monkeypatch, storage)


def _write_marker(
    checkout_dir: Path,
    *,
    project_name: str,
    project_key: str,
    primary_workspace_dir: Path,
    workspace_num: int,
    registry_path: Path | None = None,
) -> Path:
    marker_dir = checkout_dir / ".sase"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / "checkout.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_key,
                "workspace_num": workspace_num,
                "primary_workspace_dir": str(primary_workspace_dir),
                "registry_path": str(
                    registry_path
                    if registry_path is not None
                    else checkout_dir / "registry.json"
                ),
            }
        )
    )
    return marker_path


def test_canonical_project_beads_dir_non_vc_primary_only(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase" / "sdd" / "beads").mkdir(parents=True)
    _set_sdd_config(monkeypatch, storage="local")

    result = _canonical_project_beads_dir(primary)

    assert result == primary / ".sase" / "sdd" / "beads"


def test_canonical_project_beads_dir_uses_plans_companion(
    tmp_path: Path,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    primary = tmp_path / "project"
    primary.mkdir()
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "companion_repos",
            "provider": "github",
            "companions": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
            },
        },
    )
    beads = primary / "sase" / "repos" / "plans" / "beads"
    beads.mkdir(parents=True)

    assert _canonical_project_beads_dir(primary) == beads


def test_current_or_primary_beads_dir_prefers_current_checkout(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / "sdd/beads").mkdir(parents=True)
    (workspace_2 / "sdd/beads").mkdir(parents=True)

    result = _current_or_primary_beads_dir(workspace_2, primary)

    assert result == workspace_2 / "sdd/beads"


def test_canonical_project_beads_dir_vc_ignores_siblings_and_legacy(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    workspace_3 = tmp_path / "project_3"
    (primary / "sdd/beads").mkdir(parents=True)
    (workspace_2 / ".sase_beads").mkdir(parents=True)
    (workspace_3 / "sdd/beads").mkdir(parents=True)
    (workspace_3 / ".sase_beads").mkdir(parents=True)

    result = _canonical_project_beads_dir(primary)

    assert result == primary / "sdd/beads"


def test_canonical_project_beads_dir_non_vc_ignores_legacy_siblings(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    workspace_2 = tmp_path / "project_2"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (workspace_2 / ".sase_beads").mkdir(parents=True)
    _set_sdd_config(monkeypatch, storage="local")

    result = _canonical_project_beads_dir(primary)

    assert result == primary / ".sase" / "sdd" / "beads"


def test_canonical_project_beads_dir_treats_bare_git_as_vc(
    tmp_path: Path, monkeypatch
) -> None:
    primary = tmp_path / "project"
    (primary / ".sase" / "sdd" / "beads").mkdir(parents=True)
    (primary / "sdd/beads").mkdir(parents=True)
    _set_sdd_config(monkeypatch, storage="auto")
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "bare_git")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: "in_tree" if vcs_name == "bare_git" else None,
    )

    result = _canonical_project_beads_dir(primary)

    assert result == primary / "sdd/beads"


def test_get_project_beads_dirs_for_project_uses_explicit_project(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "zorg"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    sibling = tmp_path / "workspaces" / f"{project_name}_2"
    (primary / "sdd/beads").mkdir(parents=True)
    (sibling / ".sase_beads").mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = get_project_beads_dirs_for_project(project_name)

    assert result == [primary / "sdd/beads"]


def test_get_all_project_beads_dirs_dedupes_known_project_dirs(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _set_sdd_config(monkeypatch, storage="auto")
    shared_primary = tmp_path / "workspaces" / "shared"
    unique_primary = tmp_path / "workspaces" / "unique"
    (shared_primary / "sdd/beads").mkdir(parents=True)
    (unique_primary / ".sase/sdd/beads").mkdir(parents=True)

    for project_name, primary in {
        "alpha": shared_primary,
        "beta": shared_primary,
        "gamma": unique_primary,
    }.items():
        project_dir = tmp_path / ".sase" / "projects" / project_name
        project_dir.mkdir(parents=True)
        (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = get_all_project_beads_dirs()

    assert result == [
        shared_primary / "sdd/beads",
        unique_primary / ".sase" / "sdd" / "beads",
    ]


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
    (projects_dir / "myproj.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = _resolve_by_scanning_projects(str(primary / "subdir"))
    assert result == primary


def test_scanning_projects_numbered_variant(tmp_path: Path, monkeypatch) -> None:
    """CWD is under a numbered workspace variant."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "myproj"
    projects_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "myproj" / "src"
    primary.mkdir(parents=True)
    (projects_dir / "myproj.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

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
    (projects_dir / "yserve.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    cwd_variant = tmp_path / "workspaces" / "yserve_101" / "google3"
    cwd_variant.mkdir(parents=True)

    result = _resolve_by_scanning_projects(str(cwd_variant))
    assert result == primary


def test_scanning_projects_primary_not_on_disk(tmp_path: Path, monkeypatch) -> None:
    """Project name should resolve even when primary workspace doesn't exist on disk."""
    monkeypatch.setenv("HOME", str(tmp_path))
    projects_dir = tmp_path / ".sase" / "projects" / "yserve"
    projects_dir.mkdir(parents=True)
    # Primary workspace path in project spec file — does NOT exist on disk.
    primary = tmp_path / "workspaces" / "yserve" / "google3"
    (projects_dir / "yserve.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

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
    (projects_dir / "myproj.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    result = _resolve_by_scanning_projects("/some/other/path")
    assert result is None


def test_resolve_primary_workspace_via_provider_when_workspace_dir_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Falls back to workspace provider when project spec lacks WORKSPACE_DIR."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text("RUNNING:\nNAME: x\n")

    primary = tmp_path / "workspaces" / project_name / "google3"
    primary.mkdir(parents=True)
    monkeypatch.chdir(primary)

    with (
        patch("sase.workspace_provider.get_workspace_name", return_value=project_name),
        patch(
            "sase.workspace_provider.detect_workflow_type", return_value="spy"
        ) as mock_detect,
        patch(
            "sase.workspace_provider.get_workspace_directory",
            return_value=str(primary),
        ) as mock_get_dir,
    ):
        result = resolve_primary_workspace()

    assert result == primary
    mock_detect.assert_called_once_with(str(project_dir / f"{project_name}.sase"))
    mock_get_dir.assert_called_once_with("spy", 1, project_name, "")


# --- Phase 6: marker-first inference ---


def test_marker_resolves_project_name_from_xdg_state(
    tmp_path: Path, monkeypatch
) -> None:
    """A managed checkout marker resolves project name without sibling parsing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "zorg"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    # Managed checkout lives under an xdg-state-style path far from primary.
    managed = tmp_path / "state" / "sase" / "workspaces" / "key" / "10"
    managed.mkdir(parents=True)
    _write_marker(
        managed,
        project_name=project_name,
        project_key="key",
        primary_workspace_dir=primary,
        workspace_num=10,
    )

    monkeypatch.chdir(managed)
    assert infer_project_name_from_cwd() == project_name


def test_marker_project_name_is_canonicalized_through_alias_map(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    project_name = "gh_acme__sase"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "sase"
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"PROJECT_NAME: sase\nWORKSPACE_DIR: {primary}\n"
    )

    managed = tmp_path / "state" / "sase" / "10"
    managed.mkdir(parents=True)
    _write_marker(
        managed,
        project_name="sase",
        project_key="key",
        primary_workspace_dir=primary,
        workspace_num=10,
    )

    monkeypatch.chdir(managed)
    assert infer_project_name_from_cwd() == project_name


def test_provider_workspace_name_is_canonicalized_through_alias_map(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    project_name = "gh_acme__sase"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / "sase"
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"PROJECT_NAME: sase\nWORKSPACE_DIR: {primary}\n"
    )

    monkeypatch.chdir(primary)
    monkeypatch.setattr(
        "sase.workspace_provider.get_workspace_name", lambda cwd: "sase"
    )

    assert infer_project_name_from_cwd() == project_name


def test_marker_primary_overrides_sibling_scan(tmp_path: Path, monkeypatch) -> None:
    """resolve_primary_workspace prefers the marker's primary over scanning."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "zorg"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    managed = tmp_path / "state" / project_name / "10"
    managed.mkdir(parents=True)
    _write_marker(
        managed,
        project_name=project_name,
        project_key="key",
        primary_workspace_dir=primary,
        workspace_num=10,
    )

    monkeypatch.chdir(managed)
    assert resolve_primary_workspace() == primary


def test_bead_lookup_prefers_current_checkout_bead_store(
    tmp_path: Path, monkeypatch
) -> None:
    """A managed checkout with its own bead store is preferred over the primary."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "zorg"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    (primary / "sdd" / "beads").mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    managed = tmp_path / "state" / project_name / "10"
    (managed / "sdd" / "beads").mkdir(parents=True)
    _write_marker(
        managed,
        project_name=project_name,
        project_key="key",
        primary_workspace_dir=primary,
        workspace_num=10,
    )

    monkeypatch.chdir(managed)
    result = get_project_beads_dirs()
    assert result == [managed / "sdd" / "beads"]


def test_sibling_scan_still_works_without_marker(tmp_path: Path, monkeypatch) -> None:
    """Legacy adjacent workspaces with no marker still resolve via scan."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name / "src"
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    # Adjacent numbered variant with no marker.
    numbered = tmp_path / "workspaces" / f"{project_name}_101" / "src"
    numbered.mkdir(parents=True)

    monkeypatch.chdir(numbered)
    assert infer_project_name_from_cwd() == project_name
    assert resolve_primary_workspace() == primary


def test_malformed_marker_is_ignored(tmp_path: Path, monkeypatch) -> None:
    """A marker with invalid JSON falls back to legacy detection."""
    monkeypatch.setenv("HOME", str(tmp_path))
    project_name = "yserve"
    project_dir = tmp_path / ".sase" / "projects" / project_name
    project_dir.mkdir(parents=True)
    primary = tmp_path / "workspaces" / project_name
    primary.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(f"WORKSPACE_DIR: {primary}\n")

    numbered = tmp_path / "workspaces" / f"{project_name}_101"
    numbered.mkdir(parents=True)
    marker_dir = numbered / ".sase"
    marker_dir.mkdir()
    (marker_dir / "checkout.json").write_text("{ not valid json")

    monkeypatch.chdir(numbered)
    # Sibling scan still resolves project from adjacent layout.
    assert infer_project_name_from_cwd() == project_name
    assert resolve_primary_workspace() == primary


def test_marker_with_unknown_project_falls_back(tmp_path: Path, monkeypatch) -> None:
    """A marker referencing an unknown project falls back to legacy paths."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # No project registered under ~/.sase/projects/ghost.
    primary = tmp_path / "workspaces" / "ghost"
    managed = tmp_path / "state" / "ghost" / "10"
    managed.mkdir(parents=True)
    _write_marker(
        managed,
        project_name="ghost",
        project_key="k",
        primary_workspace_dir=primary,
        workspace_num=10,
    )

    monkeypatch.chdir(managed)
    # Marker exists but no project file => infer returns None.
    assert infer_project_name_from_cwd() is None
