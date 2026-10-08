"""Regression tests for the discarded-work guard's "before" HEAD.

Incident ``sase-1bu.5--2``: the commit finalizer's discarded-work guard
compared each repo against a HEAD read after dispatch instead of the HEAD
from when the dirty state was scanned, so ``before_head`` always equalled
``after_head``. Every repo that went clean without a run-owned marker was
reported as ``head_not_advanced``, and the shared-clone race/published
exemption was unreachable.

These tests capture the fingerprint while the repo is dirty and prove the
guard distinguishes a foreign commit (HEAD advanced) from a revert (HEAD
did not move), at both the unit level and through the live controller.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitExecution,
    StitchCommandResult,
    execute_commit_finalizer,
)
from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import reject_discarded_dirty_work
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.declaration import _host_repository_record_set
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.declaration_store import (
    FINAL_CONTEXT_HOST_FILENAME,
    FinalizerDeclarationError,
    HostRepositoryRecord,
    host_repository_records,
    read_host_repository_file,
    write_host_repository_file,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_progress import progress_fingerprint
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from sase.macro.directives import PromptDirectives
from tests.finalizers_live_e2e_test_helpers import (
    attach_bare_remote,
    init_live_repo,
    isolate_host_config,
    load_result,
    prepare_live_env,
    real_git_stitch,
    run_controller,
    run_git,
    submit_from_context,
    use_config,
    use_real_git_stitch,
    config_for,
    commit_instance,
)
from tests.llm_provider._commit_finalizer_sibling_helpers import (
    init_git_repo,
    mark_opened_external,
)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _dirty_state(
    repo: Path,
    changed_files: tuple[str, ...],
    *,
    kind: Literal["main", "sibling", "external", "sdd"] = "main",
    name: str = "main",
) -> DirtyState:
    return DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name=name,
                path=normalize_path(str(repo)),
                changed_files=changed_files,
                kind=kind,
            ),
        ),
        details="",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(),
        details="",
    )


def _commit_foreign(repo: Path) -> None:
    _run_git(repo, "add", "-A")
    _run_git(
        repo, "commit", "-q", "-m", "commit dirty payload\n\nSASE_AGENT=other-agent"
    )


def _reject(
    before: DirtyState,
    after: DirtyState,
    fingerprint_before: tuple[tuple[str, str, tuple[str, ...]], ...],
) -> None:
    reject_discarded_dirty_work(
        before,
        after,
        fingerprint_before=fingerprint_before,
        artifacts=None,
        project_dir=before.project_dir,
        instance_id="commit",
        attempts=(),
        evidence=(),
        invoke_result=InvokeResult(content="done"),
        ledger_before=(),
    )


def test_sdd_foreign_commit_with_real_before_head_is_exempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "research"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",), kind="sdd", name="research")
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _commit_foreign(repo)

    _reject(before, _clean_state(repo), fingerprint_before)


def test_main_foreign_commit_is_missing_provenance_not_head_not_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _commit_foreign(repo)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _reject(before, _clean_state(repo), fingerprint_before)
    assert exc_info.value.code == "dirty_work_discarded"
    assert "HEAD did not advance" not in str(exc_info.value)


def test_main_revert_without_commit_still_reports_head_not_advanced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _run_git(repo, "checkout", "--", "README.md")

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _reject(before, _clean_state(repo), fingerprint_before)
    assert exc_info.value.code == "dirty_work_discarded"
    assert "HEAD did not advance" in str(exc_info.value)


def _live_config(monkeypatch: pytest.MonkeyPatch) -> None:
    use_config(monkeypatch, config_for({"commit": commit_instance()}, ("commit",)))


def _live_provider() -> MagicMock:
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired")
    provider.is_sync_in_progress.side_effect = NotImplementedError()
    provider.get_conflicted_files.side_effect = NotImplementedError()
    return provider


def _setup_main_and_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path]:
    isolate_host_config(monkeypatch, tmp_path)
    repo = init_live_repo(tmp_path / "repo")
    other = init_live_repo(tmp_path / "other")
    attach_bare_remote(repo, tmp_path / "repo.git")
    attach_bare_remote(other, tmp_path / "other.git")
    artifacts = tmp_path / "artifacts"
    prepare_live_env(monkeypatch, artifacts, repo)
    mark_opened_external(monkeypatch, artifacts, "research", other)
    (repo / "README.md").write_text("fixture\nmain work\n", encoding="utf-8")
    (other / "README.md").write_text("fixture\nside work\n", encoding="utf-8")
    return repo, other, artifacts


def _stitch_with_side_effect(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: str,
    *,
    publish_foreign: bool = True,
) -> list[str]:
    """Stitch main normally; absorb external's dirt mid-dispatch.

    The external repo's dirt is absorbed by a concurrent writer while the
    main stitch runs: either a foreign agent commit (HEAD advances, a race
    the guard must exempt once published) or a plain revert (HEAD stays
    put, still a discard). At its own turn the external repo is already
    clean, so the fake reports a conflict and the repair triage settles it
    without a commit -- the dispatcher's supported path for work that
    vanished mid-dispatch -- leaving the verdict to the post-dispatch
    guard. An unpublished foreign commit must still be refused by the
    unpushed-HEAD guard.
    """
    seen: list[str] = []

    def stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        seen.append(f"create:{repo_arg.name}")
        if repo_arg.name == "main":
            result = real_git_stitch(repo_arg, message, excludes, context)
            assert result.returncode == 0
            other = Path(repo_arg.path).parent / "other"
            if side_effect == "foreign-commit":
                run_git(other, "add", "-A")
                run_git(
                    other,
                    "commit",
                    "-q",
                    "-m",
                    "commit dirty payload\n\nSASE_AGENT=other-agent",
                )
                if publish_foreign:
                    run_git(other, "push", "-q", "origin", "HEAD")
            elif side_effect == "revert":
                run_git(other, "checkout", "--", ".")
            else:  # pragma: no cover - defensive
                raise AssertionError(f"unknown side effect {side_effect!r}")
            return result
        from sase.llm_provider.commit_finalizer_git import git_changed_files

        if not git_changed_files(repo_arg.path):
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        return real_git_stitch(repo_arg, message, excludes, context)

    def resume(repo_arg: DirtyRepo, context: object) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        return StitchCommandResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_resume", resume)
    return seen


def test_post_dispatch_foreign_race_on_external_is_exempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, other, artifacts = _setup_main_and_external(tmp_path, monkeypatch)
    seen = _stitch_with_side_effect(monkeypatch, "foreign-commit")

    _live_config(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    result = run_controller(artifacts, _live_provider())

    assert "done" in result.content
    assert seen[0] == "create:main"
    assert "create:research" in seen
    assert "resume:research" in seen
    payload = load_result(artifacts)
    assert payload["status"] == "success"
    assert "dirty_work_discarded" not in json.dumps(payload)
    assert (
        _run_git(other, "log", "--format=%B", "-1").find("SASE_AGENT=other-agent") != -1
    )


def test_post_dispatch_unpushed_foreign_race_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, other, artifacts = _setup_main_and_external(tmp_path, monkeypatch)
    _stitch_with_side_effect(monkeypatch, "foreign-commit", publish_foreign=False)

    _live_config(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, _live_provider())

    assert "ahead of its upstream with unpushed commits" in str(exc_info.value)


def test_post_dispatch_revert_on_external_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, other, artifacts = _setup_main_and_external(tmp_path, monkeypatch)
    _stitch_with_side_effect(monkeypatch, "revert")

    _live_config(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, _live_provider())

    assert exc_info.value.code == "dirty_work_discarded"
    assert "HEAD did not advance" in str(exc_info.value)


def _execute_directly(artifacts: Path) -> BuiltinCommitExecution:
    """Run the commit finalizer without the controller's freshness gate.

    The controller re-publishes context and recovers any declaration whose
    dirt changed after submit, so the finalizer's own already-clean branch
    is only reachable by driving ``execute_commit_finalizer`` directly with
    the accepted declaration on disk.
    """
    return execute_commit_finalizer(
        ConfiguredFinalizerInstance(
            instance_id="commit",
            provider_ref="builtin@commit",
        ),
        FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="plan",
            run_id="run",
            agent_id="agent-1",
            turn_nonce="nonce",
            selected=("commit",),
        ),
        provider=MagicMock(),
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
    )


def test_already_clean_foreign_race_on_external_is_exempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, other, artifacts = _setup_main_and_external(tmp_path, monkeypatch)

    _live_config(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    # A foreign agent commits the external repo's dirt after the declaration
    # was accepted but before the finalizer runs: the already-clean check
    # must use the declaration-time HEAD, not a HEAD read after dispatch.
    run_git(other, "add", "-A")
    run_git(
        other, "commit", "-q", "-m", "commit dirty payload\n\nSASE_AGENT=other-agent"
    )

    use_real_git_stitch(monkeypatch)
    execution = _execute_directly(artifacts)

    assert execution.invoke_result.content == "done"
    assert execution.result.status == "success"


def test_already_clean_revert_on_main_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, other, artifacts = _setup_main_and_external(tmp_path, monkeypatch)

    _live_config(monkeypatch)
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    submit_from_context(artifacts)
    # The main repo's dirt is reverted with no commit after submit: HEAD
    # truly stayed put, so the guard must still fail.
    run_git(repo, "checkout", "--", "README.md")

    use_real_git_stitch(monkeypatch)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        _execute_directly(artifacts)

    assert exc_info.value.code == "dirty_work_discarded"
    assert "HEAD did not advance" in str(exc_info.value)


def test_host_repository_records_capture_declaration_time_head(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    dirty = DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name="main",
                path=normalize_path(str(repo)),
                changed_files=("README.md",),
                kind="main",
            ),
        ),
        details="",
    )

    (records,) = host_repository_records(dirty)

    assert records.head == _run_git(repo, "rev-parse", "HEAD")


def test_host_repository_file_round_trips_head(tmp_path: Path) -> None:
    path = tmp_path / FINAL_CONTEXT_HOST_FILENAME
    records = (
        HostRepositoryRecord(
            obligation_id="repo-abc",
            kind="main",
            name="main",
            path="/tmp/repo",
            path_count=1,
            head="deadbeef",
        ),
    )
    write_host_repository_file(path, context_digest="digest-1", records=records)

    assert read_host_repository_file(path) == records


def test_host_repository_file_without_head_reads_as_none(tmp_path: Path) -> None:
    path = tmp_path / FINAL_CONTEXT_HOST_FILENAME
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_digest": "digest-1",
                "repositories": [
                    {
                        "obligation_id": "repo-abc",
                        "kind": "main",
                        "name": "main",
                        "path": "/tmp/repo",
                        "path_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    (record,) = read_host_repository_file(path)

    assert record.head is None


def test_host_repository_file_with_non_string_head_is_rejected(
    tmp_path: Path,
) -> None:
    path = tmp_path / FINAL_CONTEXT_HOST_FILENAME
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_digest": "digest-1",
                "repositories": [
                    {
                        "obligation_id": "repo-abc",
                        "kind": "main",
                        "name": "main",
                        "path": "/tmp/repo",
                        "path_count": 1,
                        "head": 123,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FinalizerDeclarationError) as exc_info:
        read_host_repository_file(path)
    assert exc_info.value.code == "malformed_host_repositories"


def test_host_repository_record_set_ignores_head() -> None:
    left = (
        HostRepositoryRecord(
            obligation_id="repo-abc",
            kind="external",
            name="research",
            path="/tmp/research",
            path_count=1,
            head="before-head",
        ),
    )
    right = (
        HostRepositoryRecord(
            obligation_id="repo-abc",
            kind="external",
            name="research",
            path="/tmp/research",
            path_count=1,
            head="after-head",
        ),
    )

    assert _host_repository_record_set(left) == _host_repository_record_set(right)
