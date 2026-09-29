"""Retry-resume commit-reconciliation coverage for the finalizer controller.

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

from .finalizers_commit_reconciliation_test_helpers import (
    marker,
    patch_commit_state,
    persist_and_submit_commit,
    prepare_agent_env,
    write_commit_results,
)

__all__ = [
    "test_prior_attempt_marker_proves_already_clean_retry",
    "test_unpushed_marker_resume_failure_keeps_push_diagnostic",
    "test_unpushed_marker_resumes_already_clean_retry",
]


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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", fail_after_commit
    )

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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", fail_after_commit
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_resume", resume_push
    )

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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", fail_after_commit
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_resume", resume_push
    )

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
