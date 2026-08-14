"""Legacy sibling-env coverage for the shared commit finalizer.

The finalizer is canonical on ``linked_repos`` terminology and env/markers but
still honors the deprecated ``sibling`` env vars and opened-sibling markers.
Tests here drive the finalizer through that compatibility surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV

from ._commit_finalizer_sibling_helpers import (
    add_origin,
    commit_all,
    init_bare_remote,
    init_git_repo,
    mark_opened_sibling,
    read_result_json,
    run_finalizer,
    set_agent_env,
    set_clean_main,
    write_tool_call_record,
)


def test_dirty_configured_sibling_without_open_marker_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    dirty_file = sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(sibling)
        return InvokeResult(content="finalized sibling")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized sibling"
    assert "linked repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {sibling.resolve()}" in prompts[0]
    assert dirty_file.exists()
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"


def test_dirty_configured_sibling_triggers_follow_up_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    dirty_file = sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(tmp_path / "sase-core"),
                    "workspace_dir": str(sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", sibling)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(sibling)
        return InvokeResult(content="finalized sibling")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized sibling"
    assert "linked repo core" in prompts[0]
    assert prompts[0].count("linked repo core") == 1
    assert "dirty.txt" in prompts[0]
    assert f"cd {sibling.resolve()}" in prompts[0]
    assert "/sase_git_commit" in prompts[0]


def test_opened_dirty_sibling_uses_recorded_path_when_config_omits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(sibling)
    dirty_file = sibling / "dirty.txt"
    dirty_file.write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(SIBLING_REPOS_JSON_ENV, json.dumps([]))
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", sibling)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(sibling)
        return InvokeResult(content="finalized recorded sibling")

    provider.invoke.side_effect = invoke

    result = run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content == "primary response\n\nfinalized recorded sibling"
    assert "linked repo core" in prompts[0]
    assert "dirty.txt" in prompts[0]
    assert f"cd {sibling.resolve()}" in prompts[0]
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"


def test_dirty_observed_same_repo_workspace_from_artifacts_is_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    observed = tmp_path / "sase_12"
    remote = init_bare_remote(tmp_path / "origin.git")
    init_git_repo(main)
    init_git_repo(observed)
    add_origin(main, remote)
    add_origin(observed, remote)
    artifacts_dir = tmp_path / "artifacts"
    dirty_file = observed / "sdd" / "plans" / "observed.png"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("dirty\n", encoding="utf-8")
    write_tool_call_record(
        artifacts_dir,
        {
            "cwd": str(observed),
            "tool_input_summary": {
                "command": f"python render.py {dirty_file.resolve()}"
            },
            "tool_response_summary": {},
        },
    )
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    provider = MagicMock()

    result = run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"
    assert dirty_file.exists()
    assert '"status": "clean"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_dirty_primary_sibling_checkout_is_ignored_when_workspace_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    primary_sibling = tmp_path / "sase-core"
    workspace_sibling = tmp_path / "sase-core_10"
    main.mkdir()
    init_git_repo(primary_sibling)
    init_git_repo(workspace_sibling)
    (primary_sibling / "dirty-primary.txt").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {
                    "name": "core",
                    "primary_dir": str(primary_sibling),
                    "workspace_dir": str(workspace_sibling),
                    "workspace_num": 10,
                    "workspace_strategy": "suffix",
                }
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "core", workspace_sibling)
    provider = MagicMock()

    result = run_finalizer(provider, artifacts_dir)

    provider.invoke.assert_not_called()
    assert result.content == "primary response"


def test_multiple_dirty_configured_siblings_are_listed_and_rechecked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    alpha = tmp_path / "sase-alpha_10"
    beta = tmp_path / "sase-beta_10"
    main.mkdir()
    init_git_repo(alpha)
    init_git_repo(beta)
    alpha_file = alpha / "alpha.txt"
    beta_file = beta / "beta.txt"
    alpha_file.write_text("alpha\n", encoding="utf-8")
    beta_file.write_text("beta\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {"name": "alpha", "workspace_dir": str(alpha)},
                {"name": "beta", "workspace_dir": str(beta)},
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "alpha", alpha)
    mark_opened_sibling(monkeypatch, artifacts_dir, "beta", beta)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(alpha)
        commit_all(beta)
        return InvokeResult(content="finalized siblings")

    provider.invoke.side_effect = invoke

    run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert "linked repo alpha" in prompts[0]
    assert "alpha.txt" in prompts[0]
    assert "linked repo beta" in prompts[0]
    assert "beta.txt" in prompts[0]
    assert '"status": "finalized"' in (
        artifacts_dir / "commit_finalizer_result.json"
    ).read_text(encoding="utf-8")


def test_dirty_configured_suffix_siblings_are_listed_without_open_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    alpha = tmp_path / "sase-alpha_10"
    beta = tmp_path / "sase-beta_10"
    main.mkdir()
    init_git_repo(alpha)
    init_git_repo(beta)
    alpha_file = alpha / "alpha.txt"
    beta_file = beta / "beta.txt"
    alpha_file.write_text("alpha\n", encoding="utf-8")
    beta_file.write_text("beta\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps(
            [
                {"name": "alpha", "workspace_dir": str(alpha)},
                {"name": "beta", "workspace_dir": str(beta)},
            ]
        ),
    )
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_sibling(monkeypatch, artifacts_dir, "alpha", alpha)

    prompts: list[str] = []
    provider = MagicMock()

    def invoke(prompt: str, **_: object) -> InvokeResult:
        prompts.append(prompt)
        commit_all(alpha)
        commit_all(beta)
        return InvokeResult(content="finalized siblings")

    provider.invoke.side_effect = invoke

    run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert "linked repo alpha" in prompts[0]
    assert "alpha.txt" in prompts[0]
    assert "linked repo beta" in prompts[0]
    assert "beta.txt" in prompts[0]
    assert beta_file.exists()
