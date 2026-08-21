"""Legacy static linked-repository compatibility coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    collected_dirty_state,
    init_git_repo,
    set_agent_env,
    set_clean_main,
)


def test_legacy_none_record_is_dropped_and_non_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    legacy_static = tmp_path / "chezmoi"
    main.mkdir()
    init_git_repo(legacy_static)
    (legacy_static / "dotfile").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "chezmoi",
                    "workspace_dir": str(legacy_static),
                    "workspace_strategy": "none",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = collected_dirty_state(main, artifacts_dir)

    assert state.is_clean


def test_new_linked_record_is_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    linked = main / "sase" / "repos" / "linked" / "chezmoi"
    main.mkdir()
    init_git_repo(linked)
    (linked / "dotfile").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps([{"name": "chezmoi", "workspace_dir": str(linked)}]),
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = collected_dirty_state(main, artifacts_dir)

    assert {repo.name for repo in state.repos} == {"chezmoi"}
    assert "dotfile" in state.repos[0].changed_files
