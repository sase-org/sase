"""Handoff, publication-failure, and multiple-close coverage.

Split from ``tests.test_finalizers_failed_close_recovery``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.bead.model import IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.bead.sync import push_bead_work_launch
from sase.finalizers._failed_close_recovery_assess import assess_terminal_failure
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.commit_types import failed_result
from sase.finalizers.failed_close_recovery import (
    RECOVERY_OUTCOME_FILENAME,
    STITCH_FAILED_NOTE_PREFIX,
    coordinate_failed_close_recovery,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives

from ._failed_close_recovery_helpers import (
    close_phase_with_plan,
    fail_stitch,
    machine_lane,
    prepare_commit_run,
    seed_git_store,
)
from .finalizers_protocol_harness_test_helpers import (
    run_controller,
    submit_commit,
)

__all__ = [
    "TestHandoffAndIdentity",
    "TestMultipleCloses",
    "TestPublicationFailure",
]


class TestHandoffAndIdentity:
    def test_pending_handoff_skips_assessment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
        (artifacts / PLAN_PENDING_MARKER).write_text("1\n", encoding="utf-8")
        assessment = assess_terminal_failure(
            str(artifacts),
            failure_code="stitch_failed",
            failure_message="hook failed",
        )
        assert assessment.should_recover is False
        assert assessment.reason == "pending_handoff"

    def test_human_close_without_provenance_never_recovers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
        monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        with seed_git_store(tmp_path / "beadstore") as project:
            plan = project.create("Human plan", IssueType.PLAN, tier="epic")
            phase = project.create(
                "Human phase",
                IssueType.PHASE,
                parent_id=plan.id,
                size=PhaseSize.MEDIUM,
                created_by="human",
            )
            project.close([phase.id], resolution=Resolution.DONE)
            project.close([plan.id], resolution=Resolution.DONE)
            beads_dir = project.beads_dir
        # A later agent run fails terminally; the human closes above carry
        # no provenance for it and must be left alone.
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(phase.id).status == Status.CLOSED


class TestPublicationFailure:
    def test_failed_push_retains_diagnostic_and_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._push_recovery_mutation",
                lambda _beads: SimpleNamespace(
                    pushed=False, skipped_no_remote=False, error="push refused"
                ),
            )
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        assert outcome["attempted"] is True
        assert outcome["published"] is False
        assert outcome["publication_error"] == "push refused"
        assert "retry" in outcome["error"]
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None

    def test_retry_after_publication_failure_finishes_without_duplicate_note(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._push_recovery_mutation",
                lambda _beads: SimpleNamespace(
                    pushed=False, skipped_no_remote=False, error="push refused"
                ),
            )
            with pytest.raises(BuiltinCommitFinalizerError):
                run_controller(artifacts)
            # A later retry recovers nothing new but finishes publication
            # through the real push (the failure patch above is replaced).
            monkeypatch.setattr(
                "sase.finalizers._failed_close_recovery_apply._push_recovery_mutation",
                lambda beads: push_bead_work_launch(Path(beads)),
            )
            failure = BuiltinCommitFinalizerError(
                "hook failed",
                result=failed_result("commit", "stitch_failed", "hook failed"),
                invoke_result=InvokeResult(content=""),
            )
            outcome = coordinate_failed_close_recovery(str(artifacts), failure=failure)
            assert outcome.attempted is True
            assert outcome.already_applied
            assert not outcome.recovered
            assert outcome.published is True
        with BeadProject(tmp_path / "beadstore") as project:
            failed_notes = [
                note
                for note in project.show(phase_id).notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1


class TestMultipleCloses:
    def test_every_run_close_is_recovered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        monkeypatch.setattr(
            "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            task = project.create(
                "Extra task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            plan_id, phase_id = close_phase_with_plan(project)
            project.close([task.id], resolution=Resolution.DONE)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            assert project.show(task.id).status == Status.OPEN
            assert project.show(phase_id).status == Status.OPEN
            assert project.show(plan_id).status == Status.OPEN
