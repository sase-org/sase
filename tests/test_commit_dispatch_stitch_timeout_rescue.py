"""Rescue a stitch bounds failure when the commit already landed."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.finalizers import commit_dispatch
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import RETRYABLE_DIAGNOSTIC_CODES, InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

from .finalizers_commit_reconciliation_test_helpers import (
    patch_commit_state,
    persist_and_submit_commit,
    prepare_agent_env,
)


def _repo(path: Path, *, changed_files: tuple[str, ...]) -> DirtyRepo:
    return DirtyRepo(
        name="main", path=str(path), changed_files=changed_files, kind="main"
    )


def _state(repo: DirtyRepo) -> PreparedCommitDirtyState:
    return PreparedCommitDirtyState(
        dirty_state=DirtyState(project_dir=repo.path, repos=(repo,), details="dirty")
    )


def _context(artifacts: Path) -> FinalizerExecutionContext:
    return FinalizerExecutionContext(
        artifacts_dir=str(artifacts), plan_digest="sha256:test"
    )


def _append_marker(
    artifacts: Path,
    repo: DirtyRepo,
    *,
    sha: str,
    tree: str,
) -> None:
    path = artifacts / "commit_results.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = []
    payload.append(
        {
            "cwd": repo.path,
            "result": "ok",
            "commit_sha": sha,
            "commit_tree": tree,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _accepted_envelope(repo: DirtyRepo, message: str) -> dict[str, Any]:
    return {
        "payloads": [
            {
                "instance_id": "commit",
                "payload": {
                    "repositories": [
                        {
                            "repo_id": repository_decision_id(repo),
                            "action": "commit",
                            "message": message,
                        }
                    ]
                },
            }
        ]
    }


def _install_declaration(
    monkeypatch: pytest.MonkeyPatch,
    envelope: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        commit_dispatch,
        "load_accepted_commit_declaration",
        lambda _artifacts_dir: (envelope, None, (), ()),
    )


def _dispatch(
    *,
    repo: DirtyRepo,
    artifacts: Path,
    changed_files: list[str],
    stitch_runner: Callable[
        [DirtyRepo, str, Sequence[str], FinalizerExecutionContext],
        StitchCommandResult,
    ],
    resume_runner: (
        Callable[[DirtyRepo, FinalizerExecutionContext], StitchCommandResult] | None
    ) = None,
    provider: MagicMock | None = None,
    ledger: InstanceLedger | None = None,
) -> Any:
    return dispatch_commit_decisions(
        (repo,),
        {repository_decision_id(repo): {"action": "commit", "message": "feat: x"}},
        state=_state(repo),
        context=_context(artifacts),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=repo.path,
        provider=provider or MagicMock(),
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,
        resume_runner=resume_runner
        or (lambda _repo_arg, _context_arg: StitchCommandResult(returncode=0)),
        ledger=ledger,
        prepare_dirty_state=lambda _project_dir, _artifacts: _state(
            _repo(Path(repo.path), changed_files=tuple(changed_files))
        ),
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, protected: [
            path for path in changed_files if path not in protected
        ],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )


def test_timed_out_stitch_with_landed_commit_does_not_raise(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files: list[str] = []
    sha = "a" * 40

    def stitch_runner(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        _append_marker(artifacts, repo_arg, sha=sha, tree="b" * 40)
        return StitchCommandResult(returncode=-9, timed_out=True)

    result = _dispatch(
        repo=dirty,
        artifacts=artifacts,
        changed_files=changed_files,
        stitch_runner=stitch_runner,
    )

    assert [item.code for item in result.diagnostics] == ["stitch_timeout_after_commit"]
    assert result.diagnostics[0].severity == "warning"
    assert "main" in result.diagnostics[0].message
    assert "landed" in result.diagnostics[0].message
    assert any(
        item.kind == "commit_sha" and item.value == sha for item in result.evidence
    )


def test_timed_out_stitch_without_marker_still_fails(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))

    def stitch_runner(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=-9, timed_out=True)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=["src/app.py"],
            stitch_runner=stitch_runner,
        )

    assert exc_info.value.code == "stitch_timeout"
    assert str(exc_info.value) == "sase stitch create stitch_timeout for main"


def test_output_cap_stitch_with_landed_commit_does_not_raise(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files: list[str] = []
    sha = "c" * 40

    def stitch_runner(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        _append_marker(artifacts, repo_arg, sha=sha, tree="d" * 40)
        return StitchCommandResult(returncode=-9, stdout_truncated=True)

    result = _dispatch(
        repo=dirty,
        artifacts=artifacts,
        changed_files=changed_files,
        stitch_runner=stitch_runner,
    )

    assert [item.code for item in result.diagnostics] == [
        "stitch_output_cap_after_commit"
    ]
    assert result.diagnostics[0].severity == "warning"
    assert any(
        item.kind == "commit_sha" and item.value == sha for item in result.evidence
    )


def test_timed_out_stitch_with_remaining_dirty_paths_still_fails(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files = ["src/app.py"]

    def stitch_runner(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        _append_marker(artifacts, repo_arg, sha="a" * 40, tree="b" * 40)
        return StitchCommandResult(returncode=-9, timed_out=True)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
        )

    assert exc_info.value.code == "dirty_after_stitch"


def test_post_repair_follow_up_timeout_with_landed_commit_does_not_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files = ["src/app.py"]
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    _install_declaration(monkeypatch, _accepted_envelope(dirty, "fix: repair residue"))
    stitch_messages: list[str] = []
    follow_up_sha = "c" * 40

    def stitch_runner(
        repo_arg: DirtyRepo,
        message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        stitch_messages.append(message)
        if len(stitch_messages) == 1:
            return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)
        _append_marker(
            artifacts,
            repo_arg,
            sha=follow_up_sha,
            tree="d" * 40,
        )
        changed_files.clear()
        return StitchCommandResult(returncode=-9, timed_out=True)

    def resume_runner(
        repo_arg: DirtyRepo,
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        _append_marker(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    result = _dispatch(
        repo=dirty,
        artifacts=artifacts,
        changed_files=changed_files,
        stitch_runner=stitch_runner,
        resume_runner=resume_runner,
        provider=provider,
    )

    assert stitch_messages == ["feat: x", "fix: repair residue"]
    assert [item.code for item in result.diagnostics] == ["stitch_timeout_after_commit"]
    assert any(
        item.kind == "conflict_repair_followup" and item.value == "success"
        for item in result.evidence
    )
    assert any(
        item.kind == "commit_sha" and item.value == follow_up_sha
        for item in result.evidence
    )


def test_timed_out_stitch_with_landed_commit_instance_result_is_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_commit_state(monkeypatch, repo, dirty)
    sha = "e" * 40

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        dirty["value"] = False
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": repo_arg.path,
                        "result": "ok",
                        "commit_sha": sha,
                        "commit_tree": "f" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=-9, timed_out=True)

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    persist_and_submit_commit(artifacts)
    invoke_result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert invoke_result.content == "done"
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    instance = aggregate["instances"][0]
    assert instance["status"] == "success"
    assert [item["code"] for item in instance["diagnostics"]] == [
        "stitch_timeout_after_commit"
    ]
    assert instance["diagnostics"][0]["severity"] == "warning"
    assert any(
        item["kind"] == "commit_sha" and item["value"] == sha
        for item in instance["evidence"]
    )


def test_stitch_timeout_is_not_retryable() -> None:
    assert "stitch_timeout" not in RETRYABLE_DIAGNOSTIC_CODES
    assert "stitch_output_cap" not in RETRYABLE_DIAGNOSTIC_CODES
    assert "stitch_timeout_after_commit" not in RETRYABLE_DIAGNOSTIC_CODES
