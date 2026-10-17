"""Tests for canonical configured linked repository resolution."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.linked_repos import resolve_linked_repos_for_project
from tests._linked_repo_resolution_helpers import _project_file


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
    assert repo.primary_dir == str(canon.resolve())
    assert any("core" in warning for warning in resolution.warnings)
    env = resolution.to_env()
    assert "SASE_LINKED_REPO_CORE_2_DIR" not in env
    assert "SASE_SIBLING_REPO_CORE_2_DIR" not in env


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


def test_resolution_uses_target_project_local_config_and_tracks_origins(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from sase._linked_repo_config import (
        merged_linked_entries_from_config,
        reset_linked_repo_config_caches,
        resolution_config,
    )
    from sase.config import core as config_core

    global_config = tmp_path / "config"
    global_config.mkdir()
    (global_config / "sase.yml").write_text(
        "repos:\n  linked:\n    - name: user-tool\n      path: /global/user-tool\n",
        encoding="utf-8",
    )
    project_a_parent = tmp_path / "project-a"
    project_b_parent = tmp_path / "project-b"
    primary_a = project_a_parent / "checkout"
    primary_b = project_b_parent / "checkout"
    for primary in (primary_a, primary_b):
        (primary / ".git").mkdir(parents=True)
    (primary_a / "sase").mkdir()
    (primary_a / "sase" / "sase.yml").write_text(
        "repos:\n  linked:\n    - name: x\n      path: ../x\n",
        encoding="utf-8",
    )
    (project_a_parent / "x").mkdir()
    (project_b_parent / "x").mkdir()

    monkeypatch.setattr(config_core, "CONFIG_DIR", global_config)
    monkeypatch.setattr(config_core, "_load_default_config", lambda: {})
    monkeypatch.setattr(config_core, "_load_plugin_configs", lambda: [])
    monkeypatch.setattr(config_core, "_get_overlay_paths", lambda: [])
    monkeypatch.setattr(
        config_core,
        "get_agent_owner_config_snapshot",
        lambda: SimpleNamespace(selected_overlay=None),
    )
    config_core.clear_config_cache()
    reset_linked_repo_config_caches()
    monkeypatch.chdir(primary_a)

    try:
        config_b = resolution_config(str(primary_b), None)
        entries_b, _warnings_b = merged_linked_entries_from_config(config_b)
        assert [entry["name"] for entry in entries_b] == ["user-tool"]
        assert entries_b[0]["_sase_declared_by"] == "user"

        config_a = resolution_config(str(primary_a), None)
        entries_a, _warnings_a = merged_linked_entries_from_config(config_a)
        assert [entry["name"] for entry in entries_a] == ["user-tool", "x"]
        assert [entry["_sase_declared_by"] for entry in entries_a] == [
            "user",
            "project",
        ]
    finally:
        reset_linked_repo_config_caches()
        config_core.clear_config_cache()
