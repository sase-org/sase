"""Conflict-repair edge and failure cases for multi-repo finalizer protocol."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.runner_reporting import write_error_report
from sase.core.finalizer_wire import FinalizerInstanceResultWire
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

from .finalizers_protocol_harness_test_helpers import (
    append_commit_result,
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    submit_current_dirty,
)


def test_conflict_repair_handoff_missing_declaration_names_landed_sha(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    sibling = dirty_repo(linked, name="sase-core", kind="sibling")
    dirty = {"repos": (main,)}
    patch_dirty(monkeypatch, repo, dirty)

    def run_stitch(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        dirty["repos"] = (sibling,)
        (artifacts / "final_submission.json").unlink()
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired without declaring")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, provider)

    rendered = str(exc_info.value)
    assert "a" * 40 in rendered
    assert "sase-core" in rendered
    assert "src/app.py" in rendered
    report_path = write_error_report(
        str(tmp_path),
        agent_model=None,
        agent_llm_provider=None,
        workflow_name="commit",
        cl_name="test",
        duration="1s",
        error_summary=rendered,
        error_traceback=None,
    )
    assert report_path is not None
    report = Path(report_path).read_text(encoding="utf-8")
    assert "a" * 40 in report
    assert "sase-core" in report


def test_conflict_repair_continuation_conflict_does_not_launch_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    sibling = dirty_repo(linked, name="sase-core", kind="sibling")
    dirty = {"repos": (main,)}
    patch_dirty(monkeypatch, repo, dirty)
    seen: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        seen.append(repo_arg.name)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        dirty["repos"] = (sibling,)
        submit_current_dirty(artifacts, message="fix(core): remaining after repair")
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="continuation bound"):
        run_controller(artifacts, provider)

    assert seen == ["main", "resume:main", "sase-core"]
    assert provider.invoke.call_count == 1


def test_same_repo_second_conflict_after_repair_later_cycle_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo, name="main"),)}
    patch_dirty(monkeypatch, repo, dirty)
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    mutate = ConfiguredFinalizerInstance(
        instance_id="mutate",
        provider_ref="builtin@command",
        after=("commit",),
        config={"command": ["true"], "submission": "none"},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit", "mutate"),
        required=(),
        instances={"commit": commit, "mutate": mutate},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    attempt_fingerprints = {"value": {"src/app.py": ("M", "before-repair")}}
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.dirty_path_fingerprints",
        lambda _path: dict(attempt_fingerprints["value"]),
    )
    seen: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        seen.append(repo_arg.name)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        dirty["repos"] = ()
        append_commit_result(artifacts, repo_arg, sha="a" * 40, tree="b" * 40)
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def run_mutate(*_args: object, **_kwargs: object) -> FinalizerInstanceResultWire:
        dirty["repos"] = (dirty_repo(repo, name="main"),)
        attempt_fingerprints["value"] = {"src/app.py": ("M", "after-repair")}
        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    monkeypatch.setattr(
        "sase.finalizers.controller.execute_non_commit_finalizer",
        run_mutate,
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, provider)

    assert exc_info.value.code == "second_unresolved_conflict"
    assert "second unresolved conflict in main" in str(exc_info.value)
    assert seen == ["main", "resume:main", "main"]
    assert provider.invoke.call_count == 1
