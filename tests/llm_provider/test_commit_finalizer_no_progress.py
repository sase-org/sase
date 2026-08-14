"""Regression coverage for the commit-finalizer async-wait deadlock.

An agent that ends a finalizer pass without committing and without changing
the working tree used to burn every remaining pass "waiting for a
notification" that a fresh, non-interactive process can never deliver. The
finalizer now fingerprints each pass's progress, escalates the follow-up
prompt when a pass stalls, and records the stall in its result artifact.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer import (
    CommitFinalizerError,
    run_commit_finalizer,
)
from sase.llm_provider.types import InvokeResult

from ._commit_finalizer_sibling_helpers import read_result_json, set_agent_env


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_repo_with_dirty_file(repo: Path) -> Path:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    tracked = repo / "tracked.txt"
    tracked.write_text("original\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    tracked.write_text("dirty\n", encoding="utf-8")
    return tracked


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )


def _run_finalizer(provider: MagicMock, artifacts_dir: Path) -> InvokeResult:
    return run_commit_finalizer(
        provider=provider,
        original_prompt="primary prompt",
        invoke_result=InvokeResult(content="primary response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts_dir),
    )


def test_stalled_agent_fails_with_no_progress_diagnosis(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(
        content="I'll wait for the background task to complete."
    )
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(
        CommitFinalizerError, match="Commit finalizer failed"
    ) as exc_info:
        _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 2
    assert (
        "No pass produced a commit or a working-tree change, which indicates "
        "the agent ended each pass without committing." in str(exc_info.value)
    )
    result = read_result_json(artifacts_dir)
    assert result["status"] == "failed"
    assert result["no_progress_passes"] == 2


def test_escalation_text_appears_only_after_a_stalled_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="still working on it")
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(CommitFinalizerError):
        _run_finalizer(provider, artifacts_dir)

    prompts = [call.args[0] for call in provider.invoke.call_args_list]
    assert len(prompts) == 2
    for prompt in prompts:
        assert "non-interactive, single-turn invocation" in prompt
        assert "Never end this response in order to wait" in prompt

    assert "made no progress" not in prompts[0]
    assert "This is the final finalizer pass" not in prompts[0]
    assert "made no progress" in prompts[1]
    assert "This is the final finalizer pass" in prompts[1]


def test_committing_on_first_pass_emits_no_escalation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    tracked = _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()

    def invoke(*_: object, **__: object) -> InvokeResult:
        _run_git(repo, "add", "-A")
        _run_git(repo, "commit", "-q", "-m", "commit dirty file")
        return InvokeResult(content="committed")

    provider.invoke.side_effect = invoke
    artifacts_dir = tmp_path / "artifacts"

    _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    prompt = provider.invoke.call_args.args[0]
    assert "made no progress" not in prompt
    assert "This is the final finalizer pass" not in prompt
    assert tracked.read_text(encoding="utf-8") == "dirty\n"
    result = read_result_json(artifacts_dir)
    assert result["status"] == "finalized"
    assert result["no_progress_passes"] == 0


def test_resetting_dirty_work_without_commit_fails_as_discarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()

    def invoke(*_: object, **__: object) -> InvokeResult:
        _run_git(repo, "checkout", "--", "tracked.txt")
        return InvokeResult(content="reset dirty work")

    provider.invoke.side_effect = invoke
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(CommitFinalizerError) as exc_info:
        _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    message = str(exc_info.value)
    assert "dirty work vanished without an attributable commit" in message
    assert "main" in message
    assert "tracked.txt" in message
    result = read_result_json(artifacts_dir)
    assert result["status"] == "failed"
    assert result["reason"] == "dirty_work_discarded"
    assert result["changed_files"] == ["main:tracked.txt"]


def test_foreign_agent_commit_does_not_satisfy_clean_after_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()

    def invoke(*_: object, **__: object) -> InvokeResult:
        _run_git(repo, "add", "-A")
        _run_git(
            repo,
            "commit",
            "-q",
            "-m",
            "commit dirty file\n\nSASE_AGENT=other-agent",
        )
        return InvokeResult(content="committed as a different agent")

    provider.invoke.side_effect = invoke
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(CommitFinalizerError) as exc_info:
        _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    message = str(exc_info.value)
    assert "dirty work vanished without an attributable commit" in message
    assert "no newly reachable commit was attributed to this agent" in message
    result = read_result_json(artifacts_dir)
    assert result["status"] == "failed"
    assert result["reason"] == "dirty_work_discarded"


def test_current_agent_commit_satisfies_clean_after_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()

    def invoke(*_: object, **__: object) -> InvokeResult:
        _run_git(repo, "add", "-A")
        _run_git(
            repo,
            "commit",
            "-q",
            "-m",
            "commit dirty file\n\nSASE_AGENT=current-agent",
        )
        return InvokeResult(content="committed as current agent")

    provider.invoke.side_effect = invoke
    artifacts_dir = tmp_path / "artifacts"

    result = _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 1
    assert result.content.endswith("committed as current agent")
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["reason"] == "clean_after_pass"


def test_partial_progress_without_a_commit_is_not_a_stall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    other_file = repo / "other.txt"
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()

    calls = 0

    def invoke(*_: object, **__: object) -> InvokeResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            other_file.write_text("uncommitted extra\n", encoding="utf-8")
            return InvokeResult(content="made an edit, did not commit yet")
        _run_git(repo, "add", "-A")
        _run_git(repo, "commit", "-q", "-m", "commit everything")
        return InvokeResult(content="committed")

    provider.invoke.side_effect = invoke
    artifacts_dir = tmp_path / "artifacts"

    result = _run_finalizer(provider, artifacts_dir)

    assert provider.invoke.call_count == 2
    second_prompt = provider.invoke.call_args_list[1].args[0]
    assert "made no progress" not in second_prompt
    assert "This is the final finalizer pass" in second_prompt
    assert result.content.endswith("committed")
    result_json = read_result_json(artifacts_dir)
    assert result_json["status"] == "finalized"
    assert result_json["no_progress_passes"] == 0


def test_prior_output_is_labelled_terminated_not_a_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    _init_repo_with_dirty_file(repo)
    set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(
        content="I'll wait for the background job to finish."
    )
    artifacts_dir = tmp_path / "artifacts"

    with pytest.raises(CommitFinalizerError):
        _run_finalizer(provider, artifacts_dir)

    first_prompt = provider.invoke.call_args_list[0].args[0]
    assert "--- Work So Far ---" not in first_prompt
    assert "Prior, Already-Terminated Output" in first_prompt
    assert "already failed and must not be repeated" in first_prompt
