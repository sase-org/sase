"""Tests for linked repository resolution environment output."""

from __future__ import annotations

import json
from pathlib import Path

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env,
    resolve_linked_repos_for_project,
    scrub_linked_repo_env,
)
from tests._linked_repo_resolution_helpers import _project_file


def test_threads_auto_clone_and_gates_unmaterialized_env_paths(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "sase"
    linked = tmp_path / "sase-core"
    primary.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [
                {
                    "name": "core",
                    "path": "../sase-core",
                    "auto_clone": True,
                }
            ],
        },
        materialize=False,
    )

    repo = resolution.repos[0]
    assert repo.auto_clone is True
    env = resolution.to_env()
    assert "SASE_LINKED_REPO_CORE_DIR" not in env
    assert "SASE_LINKED_REPO_CORE_PRIMARY_DIR" not in env
    assert json.loads(env[LINKED_REPOS_JSON_ENV])[0]["auto_clone"] is True

    Path(repo.workspace_dir).mkdir(parents=True)
    env = resolution.to_env()
    assert env["SASE_LINKED_REPO_CORE_DIR"] == repo.workspace_dir
    assert env["SASE_LINKED_REPO_CORE_PRIMARY_DIR"] == repo.primary_dir


def test_distinct_names_with_colliding_env_names_still_alias(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for path in (primary, first, second):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)
    (tmp_path / "main_4" / "sase" / "repos" / "linked" / "sase-core").mkdir(
        parents=True
    )
    (tmp_path / "main_4" / "sase" / "repos" / "linked" / "sase.core").mkdir(
        parents=True
    )

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [
                {"name": "sase-core", "path": "../first"},
                {"name": "sase.core", "path": "../second"},
            ],
        },
        materialize=False,
    )

    env = resolution.to_env()
    assert env["SASE_LINKED_REPO_SASE_CORE_DIR"] == str(
        (tmp_path / "main_4" / "sase" / "repos" / "linked" / "sase-core").resolve()
    )
    assert env["SASE_LINKED_REPO_SASE_CORE_2_DIR"] == str(
        (tmp_path / "main_4" / "sase" / "repos" / "linked" / "sase.core").resolve()
    )


def test_env_emits_linked_and_sibling_aliases(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    core = tmp_path / "sase-core"
    primary.mkdir()
    core.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)
    (tmp_path / "sase_4" / "sase" / "repos" / "linked" / "core").mkdir(parents=True)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    env = resolution.to_env()
    workspace_dir = str(
        (tmp_path / "sase_4" / "sase" / "repos" / "linked" / "core").resolve()
    )
    primary_dir = str(core.resolve())
    assert env["SASE_LINKED_REPO_CORE_DIR"] == workspace_dir
    assert env["SASE_LINKED_REPO_CORE_PRIMARY_DIR"] == primary_dir
    assert env["SASE_SIBLING_REPO_CORE_DIR"] == workspace_dir
    assert env["SASE_SIBLING_REPO_CORE_PRIMARY_DIR"] == primary_dir
    assert env[LINKED_REPOS_JSON_ENV] == env[SIBLING_REPOS_JSON_ENV]
    loaded = json.loads(env[LINKED_REPOS_JSON_ENV])
    assert [item["env_name"] for item in loaded] == ["CORE"]


def test_scrub_removes_linked_and_sibling_env() -> None:
    env = {
        LINKED_REPOS_JSON_ENV: "x",
        SIBLING_REPOS_JSON_ENV: "x",
        "SASE_LINKED_REPO_CORE_DIR": "x",
        "SASE_LINKED_REPO_CORE_PRIMARY_DIR": "x",
        "SASE_SIBLING_REPO_CORE_DIR": "x",
        "SASE_SIBLING_REPO_CORE_PRIMARY_DIR": "x",
        "UNRELATED": "keep",
    }

    scrub_linked_repo_env(env)

    assert env == {"UNRELATED": "keep"}


def test_apply_replaces_stale_inherited_env(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    core = tmp_path / "sase-core"
    primary.mkdir()
    core.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)
    (tmp_path / "sase_4" / "sase" / "repos" / "linked" / "core").mkdir(parents=True)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    env = {
        "SASE_SIBLING_REPO_STALE_DIR": "/old",
        LINKED_REPOS_JSON_ENV: "[]",
        "UNRELATED": "keep",
    }
    apply_linked_repo_env(env, resolution)

    assert "SASE_SIBLING_REPO_STALE_DIR" not in env
    assert env["UNRELATED"] == "keep"
    workspace_dir = tmp_path / "sase_4" / "sase" / "repos" / "linked" / "core"
    assert env["SASE_LINKED_REPO_CORE_DIR"] == str(workspace_dir.resolve())
    assert env["SASE_SIBLING_REPO_CORE_DIR"] == str(workspace_dir.resolve())
