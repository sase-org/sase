"""Shared helpers for conflict-repair commit dispatch tests."""

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
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
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
        prepare_dirty_state=lambda _project_dir, _artifacts: (
            _state(_repo(Path(repo.path), changed_files=tuple(changed_files)))
            if changed_files
            else PreparedCommitDirtyState(
                dirty_state=DirtyState(project_dir=repo.path, repos=(), details="")
            )
        ),
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, protected: [
            path for path in changed_files if path not in protected
        ],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )
