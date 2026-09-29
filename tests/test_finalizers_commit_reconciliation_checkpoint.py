"""Checkpoint-resume commit-reconciliation coverage for the finalizer controller.

Split from ``tests.test_finalizers_commit_reconciliation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
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

__all__ = [
    "test_pending_checkpoint_refuses_foreign_agent_before_resume",
    "test_pending_checkpoint_refuses_foreign_run_before_resume",
    "test_pending_checkpoint_refuses_same_subject_different_body",
    "test_pending_checkpoint_resumes_before_clean_acceptance",
    "test_pending_checkpoint_resumes_when_only_host_footer_tags_differ",
]


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
    message = "fix(final): reconcile commit declaration\n\nbody"
    checkpoint_message = f"{message}\n\nSASE_TYPE=stitch\nSASE_AGENT=agent-1"
    checkpoint_save(
        CommitCheckpoint(
            method="create_commit",
            payload={"message": checkpoint_message},
            cwd=str(repo),
            completed_steps=["dispatch", "file_hooks"],
            commit_sha="c" * 40,
            commit_tree="d" * 40,
            pushed=True,
            operation_id="op-hook-1",
            run_id="run-1",
            publication_agent="agent-1",
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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", unexpected_create
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_resume", resume_pending
    )

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


def test_pending_checkpoint_resumes_when_only_host_footer_tags_differ(
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
    message = "fix(final): reconcile commit declaration\n\nbody"
    checkpoint_message = (
        f"{message}\n\n"
        "SASE_BEAD=[sase-17p.5][1]\n"
        "SASE_PLAN=[202609/tool_handoff_settlement.md][2]\n"
        "SASE_TYPE=stitch\n"
        "SASE_AGENT=[agent-1][3]\n\n"
        "[1]: https://example.test/bead/sase-17p.5\n"
        "[2]: https://example.test/plan/202609/tool_handoff_settlement.md\n"
        "[3]: https://example.test/agent/agent-1\n"
    )
    checkpoint_save(
        CommitCheckpoint(
            method="create_commit",
            payload={"message": checkpoint_message, "bead_action": "close"},
            cwd=str(repo),
            completed_steps=[
                "dispatch",
                "file_hooks",
                "after_hook",
                "write_result_marker",
            ],
            commit_sha="c" * 40,
            commit_tree="d" * 40,
            pushed=True,
            operation_id="op-hook-1",
            run_id="run-1",
            publication_agent="agent-1",
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
        return StitchCommandResult(returncode=0, stdout="bead close resumed\n")

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", unexpected_create
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_resume", resume_pending
    )

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
    assert "checkpoint_payload_mismatch" not in json.dumps(aggregate)


def test_pending_checkpoint_refuses_foreign_run_before_resume(
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
            run_id="run-2",
            publication_agent="agent-1",
        ),
        str(artifacts / "commit_state.json"),
    )
    resume = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_resume", resume)

    persist_and_submit_commit(artifacts, message=message)
    with pytest.raises(BuiltinCommitFinalizerError, match="different run"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    resume.assert_not_called()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "failed"
    assert "checkpoint_run_mismatch" in json.dumps(aggregate)


def test_pending_checkpoint_refuses_foreign_agent_before_resume(
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
            publication_agent="agent-2",
        ),
        str(artifacts / "commit_state.json"),
    )
    resume = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_resume", resume)

    persist_and_submit_commit(artifacts, message=message)
    with pytest.raises(BuiltinCommitFinalizerError, match="different agent"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    resume.assert_not_called()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "failed"
    assert "checkpoint_agent_mismatch" in json.dumps(aggregate)


def test_pending_checkpoint_refuses_same_subject_different_body(
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
    subject = "fix(final): reconcile commit declaration"
    checkpoint_message = f"{subject}\n\nold body"
    accepted_message = f"{subject}\n\nnew body"
    checkpoint_save(
        CommitCheckpoint(
            method="create_commit",
            payload={"message": checkpoint_message},
            cwd=str(repo),
            completed_steps=["dispatch", "file_hooks"],
            commit_sha="c" * 40,
            commit_tree="d" * 40,
            pushed=True,
            operation_id="op-hook-1",
            run_id="run-1",
            publication_agent="agent-1",
        ),
        str(artifacts / "commit_state.json"),
    )
    resume = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_resume", resume)

    persist_and_submit_commit(artifacts, message=accepted_message)
    with pytest.raises(BuiltinCommitFinalizerError, match="accepted work"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    resume.assert_not_called()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "failed"
    assert "checkpoint_payload_mismatch" in json.dumps(aggregate)
