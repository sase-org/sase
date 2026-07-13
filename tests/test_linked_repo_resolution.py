"""Tests for canonical configured linked repository resolution."""

from __future__ import annotations

import json
from pathlib import Path

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env,
    sidecar_repo_clone_dir,
    linked_repo_clone_dir,
    resolve_linked_repos_for_project,
    sdd_sidecar_clone_dirname,
    scrub_linked_repo_env,
)


def _project_file(path: Path, primary_workspace_dir: Path) -> Path:
    path.write_text(f"WORKSPACE_DIR: {primary_workspace_dir}\nNAME: main\n")
    return path


def test_resolves_canonical_linked_repos_key(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    linked = tmp_path / "sase-core"
    primary.mkdir()
    workspace.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=10,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.primary_dir == str(linked.resolve())
    assert repo.workspace_dir == str(
        (workspace / "sase" / "repos" / "linked" / "core").resolve()
    )
    assert repo.workspace_num == 10
    assert repo.auto_clone is False


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


def test_managed_project_injects_default_sidecars(tmp_path: Path) -> None:
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
            "linked_repos": [],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert [(repo.name, repo.auto_clone) for repo in resolution.repos] == [
        ("sase--plans", True),
        ("sase--research", False),
    ]
    assert [Path(repo.workspace_dir) for repo in resolution.repos] == [
        tmp_path / "sase_4" / "sase" / "repos" / "plans",
        tmp_path / "sase_4" / "sase" / "repos" / "research",
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


def test_resolves_legacy_sibling_repos_key(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    workspace = tmp_path / "sase_10"
    linked = tmp_path / "sase-core"
    primary.mkdir()
    workspace.mkdir()
    linked.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(workspace),
        workspace_num=10,
        config={
            "workspace": {"root": "adjacent"},
            "sibling_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    assert resolution.repos[0].primary_dir == str(linked.resolve())


def test_both_keys_exact_duplicate_is_deduped(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    core = tmp_path / "sase-core"
    primary.mkdir()
    core.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../sase-core"}],
            "sibling_repos": [{"name": "core", "path": "../sase-core"}],
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    assert resolution.repos[0].name == "core"


def test_canonical_wins_for_same_name_divergent_definition(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    canon = tmp_path / "canon"
    legacy = tmp_path / "legacy"
    for path in (primary, canon, legacy):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [{"name": "core", "path": "../canon"}],
            "sibling_repos": [{"name": "core", "path": "../legacy"}],
        },
        materialize=False,
    )

    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    # Canonical linked_repos definition wins.
    assert repo.primary_dir == str(canon.resolve())
    # Non-fatal warning instead of a silent ``_2`` env alias.
    assert any("core" in warning for warning in resolution.warnings)
    env = resolution.to_env()
    assert "SASE_LINKED_REPO_CORE_2_DIR" not in env
    assert "SASE_SIBLING_REPO_CORE_2_DIR" not in env


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
    # Both JSON env vars carry the identical canonical metadata.
    assert env[LINKED_REPOS_JSON_ENV] == env[SIBLING_REPOS_JSON_ENV]
    loaded = json.loads(env[LINKED_REPOS_JSON_ENV])
    assert [item["env_name"] for item in loaded] == ["CORE"]


def test_legacy_workspace_strategy_is_ignored_with_warning(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    chezmoi = tmp_path / "home" / ".local" / "share" / "chezmoi"
    primary.mkdir()
    chezmoi.mkdir(parents=True)
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(tmp_path / "sase_10"),
        workspace_num=10,
        config={
            "workspace": {"root": "adjacent"},
            "linked_repos": [
                {
                    "name": "chezmoi",
                    "path": str(chezmoi),
                    "workspace": {"strategy": "none"},
                }
            ],
        },
        materialize=False,
    )

    repo = resolution.repos[0]
    assert repo.primary_dir == str(chezmoi.resolve())
    assert repo.workspace_dir == str(
        (tmp_path / "sase_10" / "sase" / "repos" / "linked" / "chezmoi").resolve()
    )
    assert any("deprecated workspace" in warning for warning in resolution.warnings)
    assert "workspace_strategy" not in repo.to_json_dict()


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


def test_clone_path_helpers_split_linked_and_sidecar_namespaces(
    tmp_path: Path,
) -> None:
    host = tmp_path / "main_10"
    assert linked_repo_clone_dir(host, "core") == str(
        (host / "sase" / "repos" / "linked" / "core").resolve()
    )
    assert sidecar_repo_clone_dir(host, "plans") == str(
        (host / "sase" / "repos" / "plans").resolve()
    )


def test_sidecar_dirname_uses_defaults_and_store_record(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    primary.mkdir()

    assert sdd_sidecar_clone_dirname(primary, "main--plans") == "plans"
    assert sdd_sidecar_clone_dirname(primary, "main--research") == "research"
    assert sdd_sidecar_clone_dirname(primary, "core") is None

    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "sidecars": {
                "plans": {
                    "repo": "owner/custom-plans",
                    "remote_url": "https://example.com/custom-plans.git",
                },
                "research": {
                    "repo": "custom-research",
                    "remote_url": "https://example.com/custom-research.git",
                },
            },
        },
    )

    assert sdd_sidecar_clone_dirname(primary, "custom-plans") == "plans"
    assert sdd_sidecar_clone_dirname(primary, "custom-research") == "research"
    assert sdd_sidecar_clone_dirname(primary, "main--plans") is None
