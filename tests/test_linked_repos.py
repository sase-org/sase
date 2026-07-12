"""Tests for canonical configured linked repository resolution."""

from __future__ import annotations

import errno
import json
from pathlib import Path
import shutil

import pytest

from sase.linked_repos import (
    LINKED_REPOS_JSON_ENV,
    OPENED_LINKED_FILENAME,
    OPENED_SIBLINGS_FILENAME,
    SIBLING_REPOS_JSON_ENV,
    apply_linked_repo_env,
    clear_linked_repo_clones,
    companion_repo_clone_dir,
    is_sdd_companion_repo,
    linked_repo_clone_dir,
    linked_repo_metadata_from_env,
    materialize_linked_repo_workspace,
    opened_linked_repo_names,
    opened_linked_repo_records,
    record_opened_linked_repo,
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


def test_managed_project_injects_default_companions(tmp_path: Path) -> None:
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
        tmp_path / "sase_4" / "sase" / "repos" / "sase--plans",
        tmp_path / "sase_4" / "sase" / "repos" / "sase--research",
    ]


def test_default_companions_honor_override_and_opt_out(tmp_path: Path) -> None:
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


def test_missing_default_companions_are_skipped_quietly(tmp_path: Path) -> None:
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


def test_clone_path_helpers_split_linked_and_companion_namespaces(
    tmp_path: Path,
) -> None:
    host = tmp_path / "main_10"
    assert linked_repo_clone_dir(host, "core") == str(
        (host / "sase" / "repos" / "linked" / "core").resolve()
    )
    assert companion_repo_clone_dir(host, "main--plans") == str(
        (host / "sase" / "repos" / "main--plans").resolve()
    )


def test_companion_classifier_uses_defaults_and_store_record(tmp_path: Path) -> None:
    primary = tmp_path / "main"
    primary.mkdir()

    assert is_sdd_companion_repo(primary, "main--plans")
    assert is_sdd_companion_repo(primary, "main--research")
    assert not is_sdd_companion_repo(primary, "core")

    from sase.sdd.store import write_sdd_store_record

    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "companion_repos",
            "companions": {
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

    assert is_sdd_companion_repo(primary, "custom-plans")
    assert is_sdd_companion_repo(primary, "custom-research")
    assert not is_sdd_companion_repo(primary, "main--plans")


def test_clear_linked_repo_clones_stashes_directories_and_removes_strays(
    tmp_path: Path,
) -> None:
    linked = tmp_path / "sase" / "repos" / "linked"
    cached = tmp_path / "sase" / "repos" / ".linked-cache" / "core"
    core = linked / "core"
    core.mkdir(parents=True)
    (core / "new.txt").write_text("new", encoding="utf-8")
    cached.mkdir(parents=True)
    (cached / "old.txt").write_text("old", encoding="utf-8")
    (linked / "stray.txt").write_text("remove", encoding="utf-8")

    clear_linked_repo_clones(tmp_path)

    assert list(linked.iterdir()) == []
    assert (cached / "new.txt").read_text(encoding="utf-8") == "new"
    assert not (cached / "old.txt").exists()


def test_clear_linked_repo_clones_is_noop_when_root_is_absent(tmp_path: Path) -> None:
    clear_linked_repo_clones(tmp_path)

    assert not (tmp_path / "sase" / "repos").exists()


def test_materialize_restores_linked_clone_from_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    (host / ".git" / "info").mkdir(parents=True)
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    (cached / "cached.txt").write_text("cached", encoding="utf-8")
    target = host / "sase" / "repos" / "linked" / "core"
    ensured: list[str] = []
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, path: ensured.append(path) or path,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    result = materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(target),
        workspace_num=10,
    )

    assert result == str(target.resolve())
    assert ensured == [str(target.resolve())]
    assert (target / "cached.txt").read_text(encoding="utf-8") == "cached"
    assert not cached.exists()
    exclude = host / ".git" / "info" / "exclude"
    assert "/sase/repos/" in exclude.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    "race_error",
    [
        FileNotFoundError(),
        OSError(errno.EEXIST, "parallel destination"),
        OSError(errno.ENOTEMPTY, "parallel destination"),
    ],
)
def test_materialize_cache_restore_rename_race_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race_error: OSError
) -> None:
    host = tmp_path / "main_10"
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    target = host / "sase" / "repos" / "linked" / "core"
    ensured: list[str] = []

    def racing_rename(source: object, _destination: object) -> None:
        if Path(source) == cached:
            raise race_error
        raise AssertionError(f"unexpected rename source: {source}")

    monkeypatch.setattr("sase.linked_repos.os.rename", racing_rename)
    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at",
        lambda _primary, _num, path: ensured.append(path) or path,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    result = materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(target),
        workspace_num=10,
    )

    assert result == str(target.resolve())
    assert ensured == [str(target.resolve())]


def test_materialize_corrupt_cached_clone_is_recreated_by_clone_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host = tmp_path / "main_10"
    cached = host / "sase" / "repos" / ".linked-cache" / "core"
    cached.mkdir(parents=True)
    (cached / "not-a-repo.txt").write_text("corrupt", encoding="utf-8")
    target = host / "sase" / "repos" / "linked" / "core"

    def recreate_corrupt_clone(_primary: str, _num: int, path: str) -> str:
        clone = Path(path)
        assert (clone / "not-a-repo.txt").is_file()
        shutil.rmtree(clone)
        clone.mkdir(parents=True)
        (clone / ".git").mkdir()
        return path

    monkeypatch.setattr(
        "sase.workspace_provider.utils.ensure_git_clone_at", recreate_corrupt_clone
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone", lambda *_args: None
    )

    result = materialize_linked_repo_workspace(
        primary_dir=str(tmp_path / "core"),
        workspace_dir=str(target),
        workspace_num=10,
    )

    assert result == str(target.resolve())
    assert (target / ".git").is_dir()
    assert not (target / "not-a-repo.txt").exists()


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
