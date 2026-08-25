"""Coverage for refusing a stitch dispatch that protection already emptied."""

from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path

import pytest

from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import RETRYABLE_DIAGNOSTIC_CODES, InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_baseline import FinalizerBaselineRecord
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult


def _repo(path: Path, *, changed_files: tuple[str, ...]) -> DirtyRepo:
    return DirtyRepo(
        name="main", path=str(path), changed_files=changed_files, kind="main"
    )


def _state(repo: DirtyRepo) -> PreparedCommitDirtyState:
    return PreparedCommitDirtyState(
        dirty_state=DirtyState(project_dir=repo.path, repos=(repo,), details="dirty")
    )


def _never_stitch(*_args: object, **_kwargs: object) -> StitchCommandResult:
    raise AssertionError("sase stitch create must not run when protection is exhausted")


def test_protection_exhausted_refuses_before_dispatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo, changed_files=("src/app.py",))
    ledger = InstanceLedger(instance_id="commit", max_attempts=2)
    record = FinalizerBaselineRecord(
        repo_id="main:main",
        path=str(repo),
        kind="main",
        name="main",
        scope="run_start",
        fingerprints={"src/app.py": ("M", "sha")},
        captured_at="2026-08-25T07:21:06+00:00",
    )

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        dispatch_commit_decisions(
            (dirty,),
            {repository_decision_id(dirty): {"action": "commit", "message": "fix: x"}},
            state=_state(dirty),
            context=FinalizerExecutionContext(
                artifacts_dir=str(artifacts), plan_digest="sha256:test"
            ),
            instance_id="commit",
            artifacts=artifacts,
            project_dir=str(repo),
            provider=None,
            invoke_result=InvokeResult(content=""),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            options=None,
            stitch_runner=_never_stitch,
            resume_runner=_never_stitch,
            ledger=ledger,
            prepare_dirty_state=lambda _project_dir, _artifacts: _state(dirty),
            protected_path_resolver=lambda _artifacts, _path: ("src/app.py",),
            unexpected_path_resolver=lambda _path, _protected: [],
            baseline_record_resolver=lambda _artifacts, _path: record,
        )

    exc = exc_info.value
    assert exc.code == "protected_paths_exhausted"
    assert "src/app.py" in str(exc)
    assert record.repo_id in str(exc)
    assert record.scope in str(exc)
    assert ledger.consumed == 0


def test_partial_protection_still_dispatches_remaining_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo, changed_files=("src/app.py", "docs/protected.md"))
    ledger = InstanceLedger(instance_id="commit", max_attempts=2)
    changed_files = ["src/app.py", "docs/protected.md"]
    calls: list[tuple[str, tuple[str, ...]]] = []

    def stitch_runner(
        repo_arg: DirtyRepo,
        _message: str,
        excludes: Sequence[str],
        _context: object,
    ) -> StitchCommandResult:
        calls.append((repo_arg.name, tuple(excludes)))
        changed_files[:] = [path for path in changed_files if path in excludes]
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": repo_arg.path,
                        "result": "ok",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    result = dispatch_commit_decisions(
        (dirty,),
        {repository_decision_id(dirty): {"action": "commit", "message": "fix: x"}},
        state=_state(dirty),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts), plan_digest="sha256:test"
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(repo),
        provider=None,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,
        resume_runner=_never_stitch,
        ledger=ledger,
        prepare_dirty_state=lambda _project_dir, _artifacts: _state(
            _repo(repo, changed_files=tuple(changed_files))
        ),
        protected_path_resolver=lambda _artifacts, _path: ("docs/protected.md",),
        unexpected_path_resolver=(
            lambda _path, protected: [p for p in changed_files if p not in protected]
        ),
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert calls == [("main", ("docs/protected.md",))]
    assert result.attempt_id is not None
    assert ledger.consumed == 1


def test_protected_paths_exhausted_is_not_retryable() -> None:
    assert "protected_paths_exhausted" not in RETRYABLE_DIAGNOSTIC_CODES
