"""Conflict-repair follow-up commit coverage for builtin@commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.axe.runner_reporting import write_error_report
from sase.finalizers import commit_dispatch
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT


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
    resume_runner: Callable[
        [DirtyRepo, FinalizerExecutionContext], StitchCommandResult
    ],
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
        resume_runner=resume_runner,
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


def test_conflict_repair_followup_commit_uses_repair_declaration(
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
    ledger = InstanceLedger(instance_id="commit", max_attempts=2)
    _install_declaration(monkeypatch, _accepted_envelope(dirty, "fix: repair residue"))
    stitch_messages: list[str] = []

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
            sha="c" * 40,
            tree="d" * 40,
        )
        changed_files.clear()
        return StitchCommandResult(returncode=0, stdout="follow-up\n")

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
        ledger=ledger,
    )

    assert stitch_messages == ["feat: x", "fix: repair residue"]
    assert provider.invoke.call_count == 1
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert [marker["commit_sha"] for marker in markers] == ["a" * 40, "c" * 40]
    assert ledger.consumed == 1
    assert any(
        item.kind == "conflict_repair_followup" and item.value == "success"
        for item in result.evidence
    )


def test_conflict_repair_residue_without_declaration_fails_actionably(
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
    _install_declaration(
        monkeypatch,
        {"payloads": [{"instance_id": "commit", "payload": {"repositories": []}}]},
    )
    stitch_calls = 0

    def stitch_runner(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        nonlocal stitch_calls
        stitch_calls += 1
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)

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
        return StitchCommandResult(returncode=0)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=resume_runner,
            provider=provider,
        )

    exc = exc_info.value
    assert exc.code == "dirty_after_stitch"
    assert stitch_calls == 1
    assert "sase stitch create left uncommitted attributable paths in main" in str(exc)
    assert "a" * 40 in str(exc)
    assert "submitted no commit declaration for this repository" in str(exc)
    report_path = write_error_report(
        str(tmp_path),
        agent_model=None,
        agent_llm_provider=None,
        workflow_name="commit",
        cl_name="test",
        duration="1s",
        error_summary=str(exc),
        error_traceback=None,
    )
    assert report_path is not None
    rendered = Path(report_path).read_text(encoding="utf-8")
    assert "The primary commit for main already landed" in rendered
    assert "src/app.py" in rendered
    assert "submitted no commit declaration for this repository" in rendered


def test_conflict_repair_followup_that_stays_dirty_fails_once(
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
            sha="c" * 40,
            tree="d" * 40,
        )
        return StitchCommandResult(returncode=0)

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
        return StitchCommandResult(returncode=0)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=resume_runner,
            provider=provider,
        )

    assert exc_info.value.code == "dirty_after_stitch"
    assert stitch_messages == ["feat: x", "fix: repair residue"]
    assert "follow-up commit still left these paths dirty" in str(exc_info.value)


def test_conflict_repair_followup_conflict_does_not_launch_second_repair(
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

    def stitch_runner(
        _repo_arg: DirtyRepo,
        message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        stitch_messages.append(message)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)

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
        return StitchCommandResult(returncode=0)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=resume_runner,
            provider=provider,
        )

    assert exc_info.value.code == "second_unresolved_conflict"
    assert stitch_messages == ["feat: x", "fix: repair residue"]
    assert provider.invoke.call_count == 1


def test_non_conflict_dirty_after_stitch_message_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files = ["src/app.py"]
    monkeypatch.setattr(
        commit_dispatch,
        "load_accepted_commit_declaration",
        lambda _artifacts_dir: (_ for _ in ()).throw(
            AssertionError("non-conflict residue must not load a declaration")
        ),
    )

    def stitch_runner(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        _append_marker(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=lambda _repo_arg, _context_arg: StitchCommandResult(
                returncode=0
            ),
        )

    assert str(exc_info.value) == (
        "sase stitch create left uncommitted attributable paths in main: src/app.py"
    )


def test_conflict_repair_declaration_load_failure_degrades_to_dirty_after_stitch(
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
    monkeypatch.setattr(
        commit_dispatch,
        "load_accepted_commit_declaration",
        lambda _artifacts_dir: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    stitch_calls = 0

    def stitch_runner(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        nonlocal stitch_calls
        stitch_calls += 1
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)

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
        return StitchCommandResult(returncode=0)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=resume_runner,
            provider=provider,
        )

    assert exc_info.value.code == "dirty_after_stitch"
    assert stitch_calls == 1
    assert "the declaration could not be loaded: boom" in str(exc_info.value)
