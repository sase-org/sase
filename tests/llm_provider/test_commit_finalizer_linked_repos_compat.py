"""Canonical linked-repo and legacy marker compatibility tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    collected_dirty_state,
    init_git_repo,
    mark_opened_linked,
    set_agent_env,
    set_clean_main,
    write_legacy_opened_siblings_marker,
)


def test_dirty_configured_linked_env_is_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical ``linked_repos`` env and marker drive dirty discovery."""
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        LINKED_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(linked),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_linked(monkeypatch, artifacts_dir, "core", linked)
    (linked / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    state = collected_dirty_state(main, artifacts_dir)

    assert {repo.name for repo in state.repos} == {"core"}


def test_dirty_configured_linked_env_without_open_marker_is_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suffix-strategy linked workspaces block even if no opened marker exists."""
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    (linked / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        LINKED_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(linked),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    assert not (artifacts_dir / "opened_linked_workspaces.json").exists()

    state = collected_dirty_state(main, artifacts_dir)

    assert {repo.name for repo in state.repos} == {"core"}


def test_legacy_sibling_env_and_legacy_only_marker_drive_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old ``sibling`` env plus an ``opened_siblings.json``-only marker still work."""
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    (linked / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.delenv(LINKED_REPOS_JSON_ENV, raising=False)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(linked),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    write_legacy_opened_siblings_marker(artifacts_dir, "core", linked)
    assert not (artifacts_dir / "opened_linked_workspaces.json").exists()

    state = collected_dirty_state(main, artifacts_dir)

    assert {repo.name for repo in state.repos} == {"core"}
