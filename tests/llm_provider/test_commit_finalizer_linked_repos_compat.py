"""Canonical linked-repo and legacy marker compatibility tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    commit_all,
    init_git_repo,
    mark_opened_linked,
    read_result_json,
    run_finalizer,
    set_agent_env,
    set_clean_main,
    write_legacy_opened_siblings_marker,
)


def test_dirty_configured_linked_env_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Canonical ``linked_repos`` env and marker drive finalizer behavior."""
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    dirty_file = linked / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
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

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(linked)
        return InvokeResult(content="finalized linked")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized linked"
    assert "linked repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {linked.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]


def test_dirty_configured_linked_env_without_open_marker_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suffix-strategy linked workspaces block even if no opened marker exists."""
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    dirty_file = linked / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
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
    assert not (artifacts_dir / "opened_linked_workspaces.json").exists()

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(linked)
        return InvokeResult(content="finalized linked")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized linked"
    assert "linked repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {linked.resolve()}" in prompts[0]
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"


def test_legacy_sibling_env_and_legacy_only_marker_drive_finalizer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old ``sibling`` env plus an ``opened_siblings.json``-only marker still work.

    Neither the canonical ``SASE_LINKED_REPOS_JSON`` env nor the canonical
    ``opened_linked_workspaces.json`` marker is present, proving rollback-safe
    mixed-version tooling continues to drive the finalizer.
    """
    main = tmp_path / "sase_10"
    linked = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(linked)
    dirty_file = linked / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
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

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(linked)
        return InvokeResult(content="finalized via legacy marker")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized via legacy marker"
    assert "linked repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {linked.resolve()}" in prompts[0]
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"
