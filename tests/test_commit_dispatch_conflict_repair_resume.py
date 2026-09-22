"""Resume-without-marker coverage for builtin@commit conflict repair."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerObligationWire,
)
from sase.finalizers import commit_dispatch
from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.declaration_store import HostRepositoryRecord
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from tests._commit_dispatch_conflict_repair_helpers import (
    _append_marker,
    _dispatch,
    _repo,
)


def test_conflict_repair_resume_without_marker_succeeds_when_repo_settled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    changed_files: list[str] = []
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    provider.is_sync_in_progress.return_value = False
    provider.get_conflicted_files.return_value = []
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.git_changed_files",
        lambda _path: list(changed_files),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.git_head_commit_id",
        lambda _path: "h" * 40,
    )

    def stitch_runner(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)

    def resume_runner(
        _repo_arg: DirtyRepo,
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=0, stdout="nothing to finish\n")

    result = _dispatch(
        repo=dirty,
        artifacts=artifacts,
        changed_files=changed_files,
        stitch_runner=stitch_runner,
        resume_runner=resume_runner,
        provider=provider,
    )

    assert any(
        item.kind == "conflict_repair" and item.value == "resolved_without_commit"
        for item in result.evidence
    )
    assert any(
        item.kind == "head_sha" and item.value == "h" * 40 for item in result.evidence
    )
    assert not (artifacts / "commit_results.json").exists()


@pytest.mark.parametrize(
    ("sync_in_progress", "conflicted_files", "changed_files"),
    [
        (True, [], []),
        (False, ["src/app.py"], []),
        (False, [], ["src/app.py"]),
    ],
)
def test_conflict_repair_resume_without_marker_fails_when_repo_unsettled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sync_in_progress: bool,
    conflicted_files: list[str],
    changed_files: list[str],
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dirty = _repo(repo_path, changed_files=("src/app.py",))
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    provider.is_sync_in_progress.return_value = sync_in_progress
    provider.get_conflicted_files.return_value = conflicted_files
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.git_changed_files",
        lambda _path: list(changed_files),
    )

    def stitch_runner(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)

    def resume_runner(
        _repo_arg: DirtyRepo,
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=0, stdout="nothing to finish\n")

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _dispatch(
            repo=dirty,
            artifacts=artifacts,
            changed_files=changed_files,
            stitch_runner=stitch_runner,
            resume_runner=resume_runner,
            provider=provider,
        )

    assert exc_info.value.code == "missing_commit_result"


def test_conflict_repair_resume_without_marker_hands_off_new_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    linked_path = tmp_path / "linked"
    linked_path.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    main = DirtyRepo(
        name="main", path=str(repo_path), changed_files=("src/app.py",), kind="main"
    )
    linked = DirtyRepo(
        name="sase-core",
        path=str(linked_path),
        changed_files=("src/app.py",),
        kind="sibling",
    )
    live_repos: dict[str, tuple[DirtyRepo, ...]] = {"value": (main,)}
    linked_id = repository_decision_id(linked)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")
    provider.is_sync_in_progress.return_value = False
    provider.get_conflicted_files.return_value = []
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.git_changed_files",
        lambda path: (
            ["src/app.py"]
            if any(item.path == path for item in live_repos["value"])
            else []
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.git_head_commit_id",
        lambda _path: "h" * 40,
    )
    envelope = {
        "payloads": [
            {
                "instance_id": "commit",
                "payload": {
                    "repositories": [
                        {
                            "repo_id": linked_id,
                            "action": "commit",
                            "message": "fix: linked after settle",
                            "bead_action": "keep",
                        }
                    ]
                },
            }
        ]
    }
    accepted_context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest="0" * 64,
        obligations=[
            FinalizerObligationWire(
                obligation_id=linked_id,
                kind="repository",
                display_name="sibling:sase-core",
                paths=["src/app.py"],
            )
        ],
    )
    host_records = (
        HostRepositoryRecord(
            obligation_id=linked_id,
            kind="sibling",
            name="sase-core",
            path=str(linked_path),
        ),
    )
    monkeypatch.setattr(
        commit_dispatch,
        "load_accepted_commit_declaration",
        lambda _artifacts_dir: (envelope, accepted_context, host_records, ()),
    )
    stitch_names: list[str] = []

    def stitch_runner(
        repo_arg: DirtyRepo,
        message: str,
        _excludes: Sequence[str],
        _context_arg: FinalizerExecutionContext,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        stitch_names.append(repo_arg.name)
        if repo_arg.name == "main":
            return StitchCommandResult(returncode=EXIT_CODE_CONFLICT)
        live_repos["value"] = ()
        _append_marker(artifacts, repo_arg, sha="c" * 40, tree="d" * 40)
        assert message == "fix: linked after settle"
        assert bead_action == "keep"
        return StitchCommandResult(returncode=0, stdout="linked\n")

    def resume_runner(
        _repo_arg: DirtyRepo,
        _context_arg: FinalizerExecutionContext,
    ) -> StitchCommandResult:
        live_repos["value"] = (linked,)
        return StitchCommandResult(returncode=0, stdout="nothing to finish\n")

    def prepare_dirty_state(
        _project_dir: str, _artifacts: Path | None
    ) -> PreparedCommitDirtyState:
        repos = live_repos["value"]
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(
                project_dir=str(repo_path),
                repos=repos,
                details="dirty" if repos else "",
            )
        )

    result = dispatch_commit_decisions(
        (main,),
        {repository_decision_id(main): {"action": "commit", "message": "feat: x"}},
        state=PreparedCommitDirtyState(
            dirty_state=DirtyState(
                project_dir=str(repo_path), repos=(main,), details="dirty"
            )
        ),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="0" * 64,
            run_id="run-1",
            agent_id="agent-1",
            turn_nonce="nonce-1",
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(repo_path),
        provider=provider,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,
        resume_runner=resume_runner,
        ledger=None,
        prepare_dirty_state=prepare_dirty_state,
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda path, _protected: (
            ["src/app.py"]
            if any(item.path == path for item in live_repos["value"])
            else []
        ),
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert stitch_names == ["main", "sase-core"]
    assert any(
        item.kind == "conflict_repair" and item.value == "resolved_without_commit"
        for item in result.evidence
    )
    assert any(item.kind == "repair_handoff_declaration" for item in result.evidence)
