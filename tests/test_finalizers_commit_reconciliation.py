"""Commit reconciliation coverage for the finalizer controller."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.controller import run_finalizers
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.checkpoint import CommitCheckpoint, checkpoint_save

from .finalizers_commit_reconciliation_test_helpers import (
    marker,
    patch_commit_state,
    persist_and_submit_commit,
    prepare_agent_env,
    write_commit_results,
)


def test_builtin_commit_executes_declared_stitch_without_reprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    calls: list[tuple[DirtyRepo, str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append((repo_arg, message, tuple(excludes)))
        dirty["value"] = False
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo),
                        "result": "abc123",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    provider = MagicMock()

    persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=provider,
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    provider.invoke.assert_not_called()
    assert [(call[0].name, call[1], call[2]) for call in calls] == [
        ("main", "fix(final): reconcile commit declaration", ())
    ]
    assert not (artifacts / "commit_finalizer_result.json").exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert aggregate["instances"][0]["evidence"][0]["kind"] == "cwd"


def test_builtin_commit_refusal_is_rejected_before_running_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        persist_and_submit_commit(artifacts, action="refuse", reason="not mine")

    assert exc_info.value.code == "commit_action_invalid"
    runner.assert_not_called()
    assert not (artifacts / "commit_finalizer_result.json").exists()
    assert not (artifacts / "finalizer_result.json").exists()


def test_post_submit_cleanup_fails_without_proven_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    persist_and_submit_commit(artifacts)
    dirty["value"] = False
    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="vanished|discarded|attributable",
    ):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    runner.assert_not_called()


def test_stale_commit_results_do_not_prove_clean_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(repo),
                    "result": "old",
                    "commit_sha": "a" * 40,
                    "commit_tree": "b" * 40,
                }
            ]
        ),
        encoding="utf-8",
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    persist_and_submit_commit(artifacts)
    dirty["value"] = False
    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="vanished|discarded|attributable",
    ):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    runner.assert_not_called()


def test_prior_attempt_marker_proves_already_clean_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    calls = {"n": 0}

    def fail_after_commit(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        dirty["value"] = False
        write_commit_results(
            artifacts,
            [marker(repo, sha="c" * 40, tree="d" * 40)],
        )
        return StitchCommandResult(returncode=1, stderr="after-commit hook failed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", fail_after_commit)

    persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert calls["n"] == 1
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"


def test_unpushed_marker_resumes_already_clean_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    calls: list[str] = []

    def fail_after_commit(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        dirty["value"] = False
        local: dict[str, object] = marker(repo, sha="c" * 40, tree="d" * 40)
        local["pushed"] = False
        local["dispatch_error"] = "git push failed: refused"
        write_commit_results(artifacts, [local])
        return StitchCommandResult(
            returncode=1,
            stderr=(
                "commit " + "c" * 40 + " created locally; git push failed: refused\n"
            ),
        )

    def resume_push(
        _repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        pushed: dict[str, object] = marker(repo, sha="c" * 40, tree="d" * 40)
        pushed["pushed"] = True
        write_commit_results(artifacts, [pushed])
        return StitchCommandResult(returncode=0, stdout="pushed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", fail_after_commit)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume_push)

    persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert calls == ["create", "resume"]
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert [item["attempt"] for item in aggregate["instances"][0]["attempts"]] == [
        1,
        2,
    ]
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert markers[0]["pushed"] is True
    assert "dirty_work_discarded" not in json.dumps(aggregate)


def test_unpushed_marker_resume_failure_keeps_push_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    calls: list[str] = []

    def fail_after_commit(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        dirty["value"] = False
        local: dict[str, object] = marker(repo, sha="c" * 40, tree="d" * 40)
        local["pushed"] = False
        local["dispatch_error"] = "git push failed: refused"
        write_commit_results(artifacts, [local])
        return StitchCommandResult(
            returncode=1,
            stderr=(
                "commit " + "c" * 40 + " created locally; git push failed: refused\n"
            ),
        )

    def resume_push(
        _repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        return StitchCommandResult(returncode=1, stderr="git push failed again\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", fail_after_commit)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume_push)

    persist_and_submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="git push failed"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert calls == ["create", "resume"]
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "failed"
    assert "stitch_failed" in json.dumps(aggregate)
    assert "dirty_work_discarded" not in json.dumps(aggregate)


def test_pending_checkpoint_resumes_before_clean_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    calls: list[str] = []
    message = "fix(final): reconcile commit declaration"
    checkpoint_save(
        CommitCheckpoint(
            method="create_commit",
            payload={"message": message},
            cwd=str(repo),
            completed_steps=["dispatch", "file_hooks"],
            commit_sha="c" * 40,
            commit_tree="d" * 40,
            pushed=True,
            operation_id="op-hook-1",
            run_id="run-1",
        ),
        str(artifacts / "commit_state.json"),
    )

    def unexpected_create(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        return StitchCommandResult(returncode=1, stderr="fresh stitch should not run")

    def resume_pending(
        _repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        dirty["value"] = False
        write_commit_results(
            artifacts,
            [marker(repo, sha="c" * 40, tree="d" * 40)],
        )
        return StitchCommandResult(returncode=0, stdout="hook resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", unexpected_create)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume_pending)

    persist_and_submit_commit(artifacts, message=message)
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert calls == ["resume"]
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert "dirty_work_discarded" not in json.dumps(aggregate)
