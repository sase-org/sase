"""Tests for canonical configured linked repository resolution."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase._linked_repo_config import (
    _merge_resolution_config,
    merged_sidecar_entries_from_config,
)
from sase.sdd.store import write_sdd_store_record
from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env,
    sidecar_repo_clone_dir,
    linked_repo_clone_dir,
    materialize_linked_repo_workspace,
    resolve_linked_repos_for_project,
    sdd_sidecar_clone_dirname,
    scrub_linked_repo_env,
)
from tests.sdd_store._helpers import clone, commit_all, init_bare_repo


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


def test_repos_linked_precedes_deprecated_aliases(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    canonical = tmp_path / "canonical"
    legacy = tmp_path / "legacy"
    sibling = tmp_path / "sibling"
    for path in (primary, canonical, legacy, sibling):
        path.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "repos": {"linked": [{"name": "core", "path": "../canonical"}]},
            "linked_repos": [{"name": "core", "path": "../legacy"}],
            "sibling_repos": [{"name": "core", "path": "../sibling"}],
        },
        materialize=False,
    )

    assert len(resolution.repos) == 1
    assert resolution.repos[0].primary_dir == str(canonical.resolve())
    assert len(resolution.warnings) == 2
    assert all("repos.linked" in warning for warning in resolution.warnings)


def test_configured_sidecar_resolves_role_slug_and_remote(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    project_file = _project_file(tmp_path / "project.sase", primary)

    resolution = resolve_linked_repos_for_project(
        project_file=str(project_file),
        workspace_dir=str(primary),
        workspace_num=4,
        config={
            "workspace": {"root": "adjacent"},
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "repo": "sase-org/shared-research",
                        "visibility": "private",
                    }
                ]
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
    assert repo.remote_url == "https://github.com/sase-org/shared-research.git"
    assert repo.primary_dir == str((primary / "sase" / "repos" / "research").resolve())
    assert repo.workspace_dir == str(
        (tmp_path / "sase_4" / "sase" / "repos" / "research").resolve()
    )


def test_configured_sidecar_ignores_poisoned_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
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
                "sidecar": [{"name": "research", "repo": "sase-org/sase--research"}]
            }
        },
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    assert resolution.repos[0].remote_url == (
        "https://github.com/sase-org/sase--research.git"
    )


def test_configured_sidecar_preserves_consistent_store_remote(tmp_path: Path) -> None:
    primary = tmp_path / "widget"
    primary.mkdir()
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
        config={
            "repos": {
                "sidecar": [{"name": "research", "repo": "sase-org/sase--research"}]
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
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "git@github.com:acme/widget.git",
        ],
        cwd=primary,
        check=True,
    )
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
        config={"repos": {"sidecar": [{"name": "research"}]}},
        materialize=False,
    )

    assert resolution.warnings == ()
    assert len(resolution.repos) == 1
    repo = resolution.repos[0]
    assert repo.name == "research"
    assert repo.slug == "widget--research"
    assert repo.remote_url == "https://github.com/acme/widget--research.git"


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
            "repos": {"sidecar": [{"name": "research", "disabled": True}]},
        },
        materialize=False,
    )

    assert [repo.name for repo in resolution.repos] == ["sase--plans"]


def test_project_sidecar_entry_overrides_global_entry_by_role(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    primary.mkdir()
    merged = _merge_resolution_config(
        {
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "repo": "sase-org/shared-research",
                        "visibility": "public",
                    }
                ]
            }
        },
        {
            "repos": {
                "sidecar": [
                    {
                        "name": "research",
                        "visibility": "private",
                        "disabled": True,
                    }
                ]
            }
        },
    )

    entries = merged_sidecar_entries_from_config(
        merged,
        primary_workspace_dir=str(primary),
    )

    assert len(entries) == 1
    assert entries[0]["repo"] == "sase-org/shared-research"
    assert entries[0]["visibility"] == "private"
    assert entries[0]["disabled"] is True


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


def test_managed_project_injects_only_default_plans_sidecar(tmp_path: Path) -> None:
    primary = tmp_path / "sase"
    plans = tmp_path / "sase--plans"
    for path in (primary, plans):
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
    ]
    assert [Path(repo.workspace_dir) for repo in resolution.repos] == [
        tmp_path / "sase_4" / "sase" / "repos" / "plans",
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

    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) == "plans"
    assert sdd_sidecar_clone_dirname(primary, "main--research", config={}) == "research"
    assert sdd_sidecar_clone_dirname(primary, "core", config={}) is None

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

    assert sdd_sidecar_clone_dirname(primary, "custom-plans", config={}) == "plans"
    assert (
        sdd_sidecar_clone_dirname(primary, "custom-research", config={}) == "research"
    )
    assert sdd_sidecar_clone_dirname(primary, "main--plans", config={}) is None

    pinned_config = {
        "repos": {"sidecar": [{"name": "research", "repo": "owner/shared-research"}]}
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


def test_sidecar_materialization_replaces_mismatched_workspace_origin(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary-sidecar"
    target = tmp_path / "workspace" / "sase" / "repos" / "research"
    expected_remote = tmp_path / "expected.git"
    wrong_remote = tmp_path / "wrong.git"
    primary.mkdir()
    target.mkdir(parents=True)
    for path, remote in ((primary, expected_remote), (target, wrong_remote)):
        subprocess.run(["git", "init", "-q"], cwd=path, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote)],
            cwd=path,
            check=True,
        )
    (target / "stale.txt").write_text("wrong clone\n", encoding="utf-8")

    result = materialize_linked_repo_workspace(
        primary_dir=str(primary),
        workspace_dir=str(target),
        workspace_num=10,
        expected_remote_url=str(expected_remote),
    )

    assert result == str(target.resolve())
    assert not (target / "stale.txt").exists()
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert origin == str(expected_remote)


def test_sidecar_materialization_replaces_mismatched_primary_origin(
    tmp_path: Path,
) -> None:
    expected_remote = tmp_path / "expected.git"
    wrong_remote = tmp_path / "wrong.git"
    expected_seed = tmp_path / "expected-seed"
    wrong_seed = tmp_path / "wrong-seed"
    target = tmp_path / "primary" / "sase" / "repos" / "research"
    init_bare_repo(expected_remote)
    init_bare_repo(wrong_remote)
    clone(expected_remote, expected_seed)
    (expected_seed / "README.md").write_text("# Shared research\n", encoding="utf-8")
    commit_all(expected_seed, "Initialize shared research")
    subprocess.run(["git", "push", "origin", "main"], cwd=expected_seed, check=True)
    clone(wrong_remote, wrong_seed)
    (wrong_seed / "stale.txt").write_text("old project research\n", encoding="utf-8")
    commit_all(wrong_seed, "Initialize old research")
    subprocess.run(["git", "push", "origin", "main"], cwd=wrong_seed, check=True)
    clone(wrong_remote, target)

    result = materialize_linked_repo_workspace(
        primary_dir=str(target),
        workspace_dir=str(target),
        workspace_num=0,
        expected_remote_url=str(expected_remote),
    )

    assert result == str(target.resolve())
    assert not (target / "stale.txt").exists()
    assert (target / "README.md").read_text(encoding="utf-8") == ("# Shared research\n")
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert origin == str(expected_remote)


def test_sidecar_materialization_preserves_dirty_mismatched_primary(
    tmp_path: Path,
) -> None:
    target = tmp_path / "primary" / "sase" / "repos" / "research"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "wrong.git")],
        cwd=target,
        check=True,
    )
    local = target / "local.md"
    local.write_text("uncommitted research\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="has local changes"):
        materialize_linked_repo_workspace(
            primary_dir=str(target),
            workspace_dir=str(target),
            workspace_num=0,
            expected_remote_url=str(tmp_path / "expected.git"),
        )

    assert local.read_text(encoding="utf-8") == "uncommitted research\n"
