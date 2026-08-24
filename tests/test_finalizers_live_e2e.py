"""Live finalizer acceptance against disposable Git repositories.

These tests drive the generic controller through real dirty-state discovery,
real git commits, and local bare remotes. Stitch dispatch uses a real-git
runner rather than the full CommitWorkflow so the suite stays hermetic.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import (
    MONITOR_PENDING_MARKER,
    PLAN_PENDING_MARKER,
    QUESTIONS_PENDING_MARKER,
)
from sase.finalizers.declaration import FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider._invoke import invoke_agent
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives

from .finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    commit_instance,
    config_for,
    init_live_repo,
    isolate_host_config,
    load_result,
    prepare_live_env,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
    use_real_git_stitch,
)


def test_live_clean_completion_has_no_recovery_or_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="done")
    provider.resolve_model_name.return_value = "model"
    monkeypatch.setattr(
        "sase.llm_provider._invoke.get_provider",
        lambda *_args, **_kwargs: provider,
    )

    result = invoke_agent(
        "do work",
        agent_type="test",
        suppress_output=True,
        artifacts_dir=str(artifacts),
        skip_preprocessing=True,
        directives=PromptDirectives(),
    )

    assert result.content == "done"
    provider.invoke.assert_called_once()
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    assert not (artifacts / "commit_results.json").exists()
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_live_dirty_commit_excludes_protected_baseline_and_pushes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "starter.txt").write_text("pre-existing\n", encoding="utf-8")
    capture_dirty_baseline(str(repo), str(artifacts))
    (repo / "agent.py").write_text("print('agent')\n", encoding="utf-8")
    use_real_git_stitch(monkeypatch)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    result = run_controller(artifacts)

    assert result.content == "done"
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert git_changed_files(str(repo)) == ["starter.txt"]
    assert (repo / "agent.py").read_text(encoding="utf-8") == "print('agent')\n"
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert len(markers) == 1
    remote_sha = run_git(
        tmp_path / "remote.git", "rev-parse", "refs/heads/main"
    ).stdout.strip()
    assert markers[0]["commit_sha"] == remote_sha
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()


def test_live_final_none_skips_commit_on_dirty_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('skip')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    _, directives = extract_prompt_directives("%final:none\nDo work")

    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    result = run_controller(artifacts)

    assert result.content == "done"
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert payload["instances"] == []
    runner.assert_not_called()
    assert git_changed_files(str(repo)) == ["agent.py"]


def test_live_refusal_is_rejected_before_controller_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.declaration import FinalizerDeclarationError

    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('keep')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_from_context(artifacts, action="refuse")

    assert exc_info.value.code == "commit_action_invalid"
    runner.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert git_changed_files(str(repo)) == ["agent.py"]
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_live_refusal_rejected_even_with_defer_policy_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.declaration import FinalizerDeclarationError

    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('keep')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    config = config_for(
        {"commit": replace(commit_instance(), refusal="defer")}, ("commit",)
    )
    use_config(monkeypatch, config)

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        submit_from_context(artifacts, action="refuse")

    assert exc_info.value.code == "commit_action_invalid"
    runner.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert git_changed_files(str(repo)) == ["agent.py"]
    assert run_git(repo, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_live_intentional_handoffs_skip_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    attach_bare_remote(repo, tmp_path / "remote.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    (repo / "agent.py").write_text("print('handoff')\n", encoding="utf-8")
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    provider = MagicMock()

    for marker in (
        PLAN_PENDING_MARKER,
        MONITOR_PENDING_MARKER,
        QUESTIONS_PENDING_MARKER,
    ):
        (artifacts / marker).write_text("1\n", encoding="utf-8")
        result = run_controller(artifacts, provider)
        assert result.content == "done"
        (artifacts / marker).unlink()

    provider.invoke.assert_not_called()
    runner.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert git_changed_files(str(repo)) == ["agent.py"]
