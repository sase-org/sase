"""Commit-finalizer coverage for workspace-local external repositories."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.linked_repos import OPENED_LINKED_FILENAME

from ._commit_finalizer_sibling_helpers import (
    collected_dirty_state,
    init_git_repo,
    mark_opened_external,
    set_agent_env,
    set_clean_main,
)


def test_dirty_external_repo_is_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    external = main / "sase" / "repos" / "external" / "gh" / "acme" / "widget"
    main.mkdir()
    init_git_repo(external)
    (external / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_external(
        monkeypatch,
        artifacts_dir,
        "gh:acme/widget",
        external,
    )

    state = collected_dirty_state(main, artifacts_dir)

    assert [repo.kind for repo in state.repos] == ["external"]
    assert state.repos[0].name == "gh:acme/widget"
    assert "dirty.txt" in state.repos[0].changed_files


def test_clean_external_repo_is_not_discovered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    external = main / "sase" / "repos" / "external" / "projects" / "dotdrop"
    main.mkdir()
    init_git_repo(external)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_external(monkeypatch, artifacts_dir, "dotdrop", external)

    state = collected_dirty_state(main, artifacts_dir)

    assert state.is_clean


def test_v2_marker_without_kind_remains_a_linked_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    linked = main / "sase" / "repos" / "linked" / "core"
    main.mkdir()
    init_git_repo(linked)
    (linked / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / OPENED_LINKED_FILENAME).write_text(
        json.dumps(
            {
                "schema_version": 2,
                "linked_repos": [
                    {"name": "core", "workspace_dir": str(linked)},
                ],
            }
        ),
        encoding="utf-8",
    )

    state = collected_dirty_state(main, artifacts_dir)

    assert [repo.kind for repo in state.repos] == ["sibling"]
    assert state.repos[0].name == "core"
