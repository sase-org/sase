"""Tests for canonical configured linked repository resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env,
    linked_repo_metadata_from_env,
    materialize_linked_repo_workspace,
    opened_linked_repo_names,
    opened_linked_repo_records,
    record_opened_linked_repo,
    resolve_linked_repo_clone_dir,
    resolve_linked_repos_for_project,
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
    assert repo.workspace_dir == str((workspace / "sase" / "repos" / "core").resolve())
    assert repo.workspace_num == 10


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
        (tmp_path / "main_4" / "sase" / "repos" / "sase-core").resolve()
    )
    assert env["SASE_LINKED_REPO_SASE_CORE_2_DIR"] == str(
        (tmp_path / "main_4" / "sase" / "repos" / "sase.core").resolve()
    )


def test_env_emits_linked_and_sibling_aliases(tmp_path: Path) -> None:
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
        },
        materialize=False,
    )

    env = resolution.to_env()
    workspace_dir = str((tmp_path / "sase_4" / "sase" / "repos" / "core").resolve())
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
        (tmp_path / "sase_10" / "sase" / "repos" / "chezmoi").resolve()
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
    workspace_dir = tmp_path / "sase_4" / "sase" / "repos" / "core"
    assert env["SASE_LINKED_REPO_CORE_DIR"] == str(workspace_dir.resolve())
    assert env["SASE_SIBLING_REPO_CORE_DIR"] == str(workspace_dir.resolve())


def test_non_materializing_resolution_falls_back_to_legacy_clone(
    tmp_path: Path,
) -> None:
    host = tmp_path / "main_10"
    legacy = host / ".sase" / "workspaces" / "core"
    legacy.mkdir(parents=True)

    assert resolve_linked_repo_clone_dir(host, "core") == str(legacy.resolve())


def test_materialize_migrates_legacy_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    (host / ".git" / "info").mkdir(parents=True)
    legacy = host / ".sase" / "workspaces" / "core"
    legacy.mkdir(parents=True)
    (legacy / "wip.txt").write_text("keep me", encoding="utf-8")
    canonical = host / "sase" / "repos" / "core"
    ensured: list[str] = []
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, target: ensured.append(target) or target,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    result = materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(legacy),
        workspace_num=10,
    )

    assert result == str(canonical)
    assert ensured == [str(canonical)]
    assert (canonical / "wip.txt").read_text(encoding="utf-8") == "keep me"
    assert not legacy.exists()
    assert not legacy.parent.exists()
    exclude = host / ".git" / "info" / "exclude"
    assert "/sase/repos/" in exclude.read_text(encoding="utf-8").splitlines()


def test_materialize_prefers_canonical_when_both_clone_paths_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    legacy = host / ".sase" / "workspaces" / "core"
    canonical = host / "sase" / "repos" / "core"
    legacy.mkdir(parents=True)
    canonical.mkdir(parents=True)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, target: target,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    with pytest.warns(RuntimeWarning, match="stale legacy clone"):
        result = materialize_linked_repo_workspace(
            primary_dir=str(tmp_path / "core"),
            workspace_dir=str(legacy),
            workspace_num=10,
        )

    assert result == str(canonical)
    assert legacy.is_dir()


def test_metadata_from_env_prefers_linked_then_falls_back() -> None:
    linked_payload = json.dumps([{"name": "core", "env_name": "CORE"}])
    sibling_payload = json.dumps([{"name": "legacy", "env_name": "LEGACY"}])

    assert linked_repo_metadata_from_env({LINKED_REPOS_JSON_ENV: linked_payload}) == [
        {"name": "core", "env_name": "CORE"}
    ]
    # Falls back to the legacy env var when the canonical one is absent.
    assert linked_repo_metadata_from_env({SIBLING_REPOS_JSON_ENV: sibling_payload}) == [
        {"name": "legacy", "env_name": "LEGACY"}
    ]
    assert linked_repo_metadata_from_env({}) == []


def test_record_opened_writes_both_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    core = tmp_path / "sase-core_10"
    nvim = tmp_path / "sase-nvim_10"

    record_opened_linked_repo(
        "core",
        str(core),
        reason=" inspect sibling changes ",
        opened_at="2026-06-20T14:00:00+00:00",
    )
    record_opened_linked_repo(
        "nvim",
        str(nvim),
        reason="check editor integration",
        opened_at="2026-06-20T14:05:00+00:00",
    )
    record_opened_linked_repo(
        "core",
        str(core),
        reason="inspect sibling changes",
        opened_at="2026-06-20T14:00:00+00:00",
    )

    linked_marker = json.loads(
        (tmp_path / OPENED_LINKED_FILENAME).read_text(encoding="utf-8")
    )
    sibling_marker = json.loads(
        (tmp_path / OPENED_SIBLINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert linked_marker["schema_version"] == 2
    assert sibling_marker["schema_version"] == 2
    assert [item["name"] for item in linked_marker["linked_repos"]] == ["core", "nvim"]
    assert [item["name"] for item in sibling_marker["siblings"]] == ["core", "nvim"]
    assert linked_marker["linked_repos"][0]["reason"] == "inspect sibling changes"
    assert linked_marker["linked_repos"][0]["opened_at"] == (
        "2026-06-20T14:00:00+00:00"
    )
    assert opened_linked_repo_names(tmp_path) == {"core", "nvim"}
    assert opened_linked_repo_records(tmp_path)["core"] == {
        "name": "core",
        "workspace_dir": str(core.resolve()),
        "reason": "inspect sibling changes",
        "opened_at": "2026-06-20T14:00:00+00:00",
    }


def test_opened_names_reads_legacy_only_marker(tmp_path: Path) -> None:
    (tmp_path / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [{"name": "core", "workspace_dir": "/tmp/core"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_names(tmp_path) == {"core"}
    assert opened_linked_repo_records(tmp_path) == {
        "core": {
            "name": "core",
            "workspace_dir": "/tmp/core",
            "reason": "",
            "opened_at": "",
        }
    }


def test_opened_names_reads_new_only_marker(tmp_path: Path) -> None:
    (tmp_path / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "linked_repos": [{"name": "core", "workspace_dir": "/tmp/core"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_names(tmp_path) == {"core"}
    assert opened_linked_repo_records(tmp_path) == {
        "core": {
            "name": "core",
            "workspace_dir": "/tmp/core",
            "reason": "",
            "opened_at": "",
        }
    }


def test_opened_records_canonical_marker_wins_over_legacy(tmp_path: Path) -> None:
    (tmp_path / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "linked_repos": [
                    {
                        "name": "core",
                        "workspace_dir": "/tmp/canonical",
                        "reason": "canonical reason",
                        "opened_at": "2026-06-20T14:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / OPENED_SIBLINGS_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "siblings": [{"name": "core", "workspace_dir": "/tmp/legacy"}],
            }
        ),
        encoding="utf-8",
    )

    assert opened_linked_repo_records(tmp_path)["core"] == {
        "name": "core",
        "workspace_dir": "/tmp/canonical",
        "reason": "canonical reason",
        "opened_at": "2026-06-20T14:00:00+00:00",
    }


def test_opened_names_handles_missing_and_malformed(tmp_path: Path) -> None:
    assert opened_linked_repo_names(tmp_path) == set()
    assert opened_linked_repo_records(tmp_path) == {}
    assert opened_linked_repo_names(None) == set()

    (tmp_path / OPENED_LINKED_FILENAME).write_text("{", encoding="utf-8")
    assert opened_linked_repo_names(tmp_path) == set()
