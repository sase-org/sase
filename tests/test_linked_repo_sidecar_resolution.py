"""Tests for resolving explicitly configured linked repository sidecars."""

from __future__ import annotations

from pathlib import Path

from sase.linked_repos import resolve_linked_repos_for_project
from sase.sdd.store import write_sdd_store_record
from tests._linked_repo_resolution_helpers import _project_file, _set_github_origin


def test_configured_sidecar_resolves_role_slug_and_remote(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/sase-org/sase.git")
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "repos": {
                "sidecar": {
                    "custom": {
                        "research": {
                            "repo": "sase-org/shared-research",
                            "visibility": "private",
                        }
                    }
                }
            },
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.name == "research"
    assert repo.kind == "sidecar"
    assert repo.slug == "shared-research"
    assert repo.remote_url == "git@github.com:sase-org/shared-research.git"
    assert repo.primary_dir == str((primary / "sase" / "repos" / "research").resolve())
    assert repo.workspace_dir == str(
        (tmp_path / "sase_4" / "sase" / "repos" / "research").resolve()
    )


def test_configured_sidecar_ignores_poisoned_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:acme/widget--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={
            "repos": {
                "sidecar": {"custom": {"research": {"repo": "sase-org/sase--research"}}}
            }
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    assert resolution.repos[0].remote_url == (
        "git@github.com:sase-org/sase--research.git"
    )


def test_configured_sidecar_preserves_consistent_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "https://github.com/acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "https://github.com/sase-org/sase--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={
            "repos": {
                "sidecar": {"custom": {"research": {"repo": "sase-org/sase--research"}}}
            }
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert resolution.repos[0].remote_url == (
        "git@github.com:sase-org/sase--research.git"
    )


def test_unpinned_configured_sidecar_ignores_stale_store_repo(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
    _set_github_origin(primary, "git@github.com:acme/widget.git")
    project_file = _project_file(tmp_path / "project.sase", primary)
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "acme/widget--plans",
                    "remote_url": "git@github.com:acme/widget--plans.git",
                },
                "research": {
                    "repo": "sase-org/sase--research",
                    "remote_url": "git@github.com:sase-org/sase--research.git",
                },
            },
        },
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=0,
        config={"repos": {"sidecar": {"custom": {"research": {}}}}},
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.name == "research"
    assert repo.slug == "widget--research"
    assert repo.remote_url == "git@github.com:acme/widget--research.git"
