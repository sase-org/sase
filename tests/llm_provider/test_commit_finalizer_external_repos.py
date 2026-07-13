"""Commit-finalizer coverage for workspace-local external repositories."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.linked_repos import OPENED_LINKED_FILENAME
from sase.llm_provider.types import InvokeResult

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    mark_opened_external,
    read_result_json,
    run_finalizer,
    set_agent_env,
    set_clean_main,
)


def test_dirty_external_repo_triggers_correctly_labeled_follow_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    external = main / "sase" / "repos" / "external" / "gh" / "acme" / "widget"
    main.mkdir()
    init_git_repo(external)
    dirty_file = external / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv("SASE_COMMIT_METHOD", "create_pull_request")
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_external(
        monkeypatch,
        artifacts_dir,
        "gh:acme/widget",
        external,
    )

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized external repo")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized external repo"
    assert "external repo `gh:acme/widget`" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {external.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]
    assert "commit method type is `create_pull_request`" in prompts[0]
    assert read_result_json(artifacts_dir)["reason"] == "clean_after_pass"


def test_clean_external_repo_does_not_trigger_follow_up(
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
    provider = MagicMock()

    result = run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert read_result_json(artifacts_dir)["reason"] == "no_changes"


def test_v2_marker_without_kind_remains_a_linked_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    linked = main / "sase" / "repos" / "linked" / "core"
    main.mkdir()
    init_git_repo(linked)
    dirty_file = linked / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
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
    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized linked repo")

    provider.invoke.side_effect = invoke

    run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert "linked repo core" in prompts[0]
    assert "external repo `core`" not in prompts[0]
