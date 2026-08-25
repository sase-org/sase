"""Tests for implicit default sidecars and sidecar clone directory names."""

from __future__ import annotations

from pathlib import Path

from sase.linked_repos import (
    resolve_linked_repos_for_project,
    sdd_sidecar_clone_dirname,
)
from sase.sdd.store import write_sdd_store_record
from tests._linked_repo_resolution_helpers import _project_file


def test_disabled_sidecar_suppresses_matching_implicit_default(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    plans = tmp_path / "sase--plans"
    research = tmp_path / "sase--research"
    for path in (primary, plans, research):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "workspace": {"root": "adjacent"},
            "repos": {"sidecar": {"custom": {"research": {"disabled": True}}}},
        },
        materialize=False,
    )

    assert [repo.name for repo in resolution.repos] == ["sase--plans"]


def test_managed_project_injects_default_plans_and_beads_sidecars(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    plans = tmp_path / "sase--plans"
    beads = tmp_path / "sase--beads"
    for path in (primary, plans, beads):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "workspace": {"root": "adjacent"},
            "linked_repos": [],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert [(repo.name, repo.auto_clone) for repo in resolution.repos] == [
        ("sase--plans", True),
        ("sase--beads", False),
    ]
    assert [Path(repo.workspace_dir) for repo in resolution.repos] == [
        tmp_path / "sase_4" / "sase" / "repos" / "plans",
        tmp_path / "sase_4" / "sase" / "repos" / "beads",
    ]


def test_default_sidecars_honor_override_and_opt_out(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    override = tmp_path / "custom-research"
    for path in (primary, override):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    overridden = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "linked_repos": [
                {
                    "name": "sase--research",
                    "path": "../custom-research",
                    "auto_clone": True,
                }
            ],
        },
        materialize=False,
    )
    assert [repo.name for repo in overridden.repos] == ["sase--research"]
    assert overridden.repos[0].primary_dir == str(override.resolve())
    assert overridden.repos[0].auto_clone is True

    opted_out = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "is_sase_managed": True,
            "default_linked_repos": False,
            "linked_repos": [],
        },
        materialize=False,
    )
    assert opted_out.repos == ()
    assert opted_out.warnings == ()


def test_missing_default_sidecars_are_skipped_quietly(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={"is_sase_managed": True, "linked_repos": []},
        materialize=False,
    )

    assert resolution.repos == ()
    assert resolution.warnings == ()


def test_sidecar_dirname_uses_defaults_and_store_record(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    primary.mkdir()

    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) == "plans"
    assert sdd_sidecar_clone_dirname(primary, "main--research", config={}) is None
    assert sdd_sidecar_clone_dirname(primary, "main--beads", config={}) == "beads"
    assert sdd_sidecar_clone_dirname(primary, "core", config={}) is None

    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "owner/custom-plans",
                    "remote_url": "git@example.com:owner/custom-plans.git",
                },
                "research": {
                    "repo": "custom-research",
                    "remote_url": "git@example.com:owner/custom-research.git",
                },
                "designs": {
                    "repo": "owner/custom-designs",
                    "remote_url": "git@example.com:owner/custom-designs.git",
                },
            },
        },
    )

    assert sdd_sidecar_clone_dirname(primary, "custom-plans", config={}) == "plans"
    assert (
        sdd_sidecar_clone_dirname(primary, "custom-research", config={}) == "research"
    )
    assert sdd_sidecar_clone_dirname(primary, "custom-designs", config={}) == "designs"
    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) is None

    pinned_config = {
        "repos": {
            "sidecar": {"custom": {"research": {"repo": "owner/shared-research"}}}
        }
    }
    assert (
        sdd_sidecar_clone_dirname(primary, "research", config=pinned_config)
        == "research"
    )
    assert (
        sdd_sidecar_clone_dirname(primary, "shared-research", config=pinned_config)
        == "research"
    )
    assert (
        sdd_sidecar_clone_dirname(primary, "custom-research", config=pinned_config)
        is None
    )
