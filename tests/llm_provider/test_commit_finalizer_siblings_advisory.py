"""Legacy static linked-repository compatibility coverage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    read_result_json,
    run_finalizer,
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
    provider = MagicMock()

    result = run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert read_result_json(artifacts_dir)["reason"] == "no_changes"


def test_new_linked_record_is_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    linked = main / "sase" / "repos" / "linked" / "chezmoi"
    main.mkdir()
    init_git_repo(linked)
    dirty_file = linked / "dotfile"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps([{"name": "chezmoi", "workspace_dir": str(linked)}]),
    )
    artifacts_dir = tmp_path / "artifacts"
    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        dirty_file.unlink()
        return InvokeResult(content="finalized linked repo")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert result.content == "primary response\n\nfinalized linked repo"
    assert "linked repo chezmoi" in prompts[0]
    assert "dotfile" in prompts[0]
    assert f"cd {linked.resolve()}" in prompts[0]
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"
