"""Provenance stamping for bead closes and its codec round-trips."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.bead import db as bead_db
from sase.bead.close_history_codec import (
    close_history_from_dicts,
    close_history_to_dicts,
)
from sase.bead.close_provenance import (
    RECOVERY_AGENT_NAME_ENV_VAR,
    RECOVERY_ARTIFACTS_DIR_ENV_VAR,
    RECOVERY_RUN_ID_ENV_VAR,
    host_run_close_provenance,
)
from sase.bead.completion_failure_codec import (
    completion_failure_from_dict,
    completion_failure_to_dict,
)
from sase.bead.jsonl import export_to_jsonl, import_from_jsonl
from sase.bead.model import (
    BeadCloseProvenance,
    BeadCompletionFailure,
    CloseRecord,
    IssueType,
    PhaseSize,
    ReopenCause,
    Resolution,
    Status,
)
from sase.bead.project import BeadProject
from sase.core import bead_mutation_facade as rust_beads
from sase.core.bead_wire import issue_from_dict

PROVENANCE = {
    "run_id": "run-77",
    "agent_name": "agent-77",
    "artifact_dir": "/tmp/run-77",
}


def _provenance(artifact_dir: str = "/tmp/run-77") -> BeadCloseProvenance:
    return BeadCloseProvenance(
        run_id="run-77", agent_name="agent-77", artifact_dir=artifact_dir
    )


def _failure() -> BeadCompletionFailure:
    return BeadCompletionFailure(
        close_event_id="beads-1:000002:issue_closed:beads-1:abc",
        run_id="run-77",
        agent_name="agent-77",
        artifact_dir="/tmp/run-77",
        failed_at="2026-10-26T20:00:00Z",
        failure_code="hook_failed",
        evidence_locations=("/tmp/run-77/finalizer_result.json",),
    )


class TestHostRunCloseProvenance:
    def test_agent_env_yields_provenance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-77")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-77")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
        assert host_run_close_provenance() == {
            "run_id": "run-77",
            "agent_name": "agent-77",
            "artifact_dir": str(tmp_path),
        }

    def test_missing_run_identity_yields_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
        monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
        assert host_run_close_provenance({}) is None

    def test_monitor_overrides_win(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-monitor")
        monkeypatch.setenv("SASE_AGENT_NAME", "monitor-agent")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "monitor"))
        monkeypatch.setenv(RECOVERY_RUN_ID_ENV_VAR, "run-77")
        monkeypatch.setenv(RECOVERY_AGENT_NAME_ENV_VAR, "agent-77")
        monkeypatch.setenv(RECOVERY_ARTIFACTS_DIR_ENV_VAR, str(tmp_path))
        assert host_run_close_provenance() == {
            "run_id": "run-77",
            "agent_name": "agent-77",
            "artifact_dir": str(tmp_path),
        }

    def test_agent_name_from_meta(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-77")
        monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
        (tmp_path / "agent_meta.json").write_text(
            json.dumps({"name": "meta-agent"}), encoding="utf-8"
        )
        assert host_run_close_provenance() == {
            "run_id": "run-77",
            "agent_name": "meta-agent",
            "artifact_dir": str(tmp_path),
        }


class TestModelValidation:
    def test_blank_provenance_fields_rejected(self) -> None:
        with pytest.raises(ValueError, match="run_id cannot be empty"):
            BeadCloseProvenance(
                run_id=" ", agent_name="a", artifact_dir="/x"
            ).validate()

    def test_blank_failure_fields_rejected(self) -> None:
        failure = _failure()
        with pytest.raises(ValueError, match="failure_code cannot be empty"):
            BeadCompletionFailure(
                close_event_id=failure.close_event_id,
                run_id=failure.run_id,
                agent_name=failure.agent_name,
                artifact_dir=failure.artifact_dir,
                failed_at=failure.failed_at,
                failure_code=" ",
            ).validate()

    def test_blank_failure_evidence_location_rejected(self) -> None:
        failure = _failure()
        with pytest.raises(ValueError, match="evidence locations"):
            BeadCompletionFailure(
                close_event_id=failure.close_event_id,
                run_id=failure.run_id,
                agent_name=failure.agent_name,
                artifact_dir=failure.artifact_dir,
                failed_at=failure.failed_at,
                failure_code=failure.failure_code,
                evidence_locations=(" ",),
            ).validate()


class TestCloseHistoryCodec:
    def test_record_round_trips_provenance(self) -> None:
        record = CloseRecord(
            closed_at="2026-10-26T19:00:00Z",
            reopened_at="2026-10-26T20:00:00Z",
            reopened_via=ReopenCause.COMPLETION_FAILURE,
            resolution=Resolution.DONE,
            reopened_by="agent-77",
            close_event_id="beads-1:000002:issue_closed:beads-1:abc",
            close_provenance=_provenance(),
        )
        decoded = close_history_from_dicts(close_history_to_dicts([record]))
        assert decoded == [record]

    def test_wire_field_order_matches_core(self) -> None:
        record = CloseRecord(
            closed_at="2026-10-26T19:00:00Z",
            reopened_at="2026-10-26T20:00:00Z",
            reopened_via=ReopenCause.COMPLETION_FAILURE,
            resolution=Resolution.DONE,
            reopened_by="agent-77",
            close_event_id="evt-1",
            close_provenance=_provenance(),
        )
        assert list(close_history_to_dicts([record])[0].keys()) == [
            "closed_at",
            "resolution",
            "reopened_at",
            "reopened_via",
            "reopened_by",
            "close_event_id",
            "close_provenance",
        ]

    def test_legacy_record_without_provenance_still_decodes(self) -> None:
        decoded = close_history_from_dicts(
            [
                {
                    "closed_at": "2026-10-26T19:00:00Z",
                    "reopened_at": "2026-10-26T20:00:00Z",
                    "reopened_via": "open",
                }
            ]
        )
        assert decoded[0].close_event_id is None
        assert decoded[0].close_provenance is None


class TestCompletionFailureCodec:
    def test_wire_dict_decodes(self) -> None:
        failure = _failure()
        wire = {
            "close_event_id": failure.close_event_id,
            "run_id": failure.run_id,
            "agent_name": failure.agent_name,
            "artifact_dir": failure.artifact_dir,
            "failed_at": failure.failed_at,
            "failure_code": failure.failure_code,
            "evidence_locations": list(failure.evidence_locations),
        }
        assert completion_failure_from_dict(wire) == failure

    def test_absence_decodes_to_none(self) -> None:
        assert completion_failure_from_dict(None) is None

    def test_to_dict_round_trips(self) -> None:
        failure = _failure()
        assert completion_failure_from_dict(completion_failure_to_dict(failure)) == (
            failure
        )


class TestIssueWireDecode:
    def test_issue_from_dict_carries_new_fields(self) -> None:
        issue = issue_from_dict(
            {
                "id": "beads-1",
                "title": "t",
                "status": "closed",
                "issue_type": "task",
                "close_event_id": "evt-1",
                "close_provenance": dict(PROVENANCE),
                "resolution": "done",
                "completion_failure": {
                    "close_event_id": "evt-1",
                    "run_id": "run-77",
                    "agent_name": "agent-77",
                    "artifact_dir": "/tmp/run-77",
                    "failed_at": "2026-10-26T20:00:00Z",
                    "evidence_locations": [],
                    "failure_code": "hook_failed",
                },
            }
        )
        assert issue.close_event_id == "evt-1"
        assert issue.close_provenance == _provenance()
        assert issue.completion_failure is not None
        assert issue.completion_failure.failure_code == "hook_failed"

    def test_issue_from_dict_tolerates_absence(self) -> None:
        issue = issue_from_dict(
            {"id": "beads-1", "title": "t", "status": "open", "issue_type": "task"}
        )
        assert issue.close_event_id is None
        assert issue.close_provenance is None
        assert issue.completion_failure is None


def _seed_git_store(root: Path) -> BeadProject:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "probe@example.invalid"], cwd=root, check=True
    )
    return BeadProject.init(root)


class TestCloseProvenanceIntegration:
    def test_close_stamps_env_provenance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-77")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-77")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
        with _seed_git_store(tmp_path / "store") as project:
            task = project.create(
                "Provenance task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            (closed,) = project.close([task.id], resolution=Resolution.DONE)
            assert closed.status == Status.CLOSED
            assert closed.close_provenance is not None
            assert closed.close_provenance.run_id == "run-77"
            assert closed.close_provenance.agent_name == "agent-77"
            assert closed.close_event_id
            assert project.show(task.id).close_provenance == closed.close_provenance

    def test_human_close_without_env_stays_unattributed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
        monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
        monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
        with _seed_git_store(tmp_path / "store") as project:
            task = project.create(
                "Human task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            (closed,) = project.close([task.id], resolution=Resolution.DONE)
            assert closed.status == Status.CLOSED
            assert closed.close_provenance is None
            assert closed.close_event_id

    def test_explicit_provenance_overrides_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-env")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-env")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
        with _seed_git_store(tmp_path / "store") as project:
            task = project.create(
                "Override task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            (closed,) = project.close(
                [task.id],
                resolution=Resolution.DONE,
                close_provenance=dict(PROVENANCE),
            )
            assert closed.close_provenance is not None
            assert closed.close_provenance.run_id == "run-77"

    def test_recover_binding_round_trip(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-77")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-77")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
        with _seed_git_store(tmp_path / "store") as project:
            task = project.create(
                "Recovery task",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            project.close([task.id], resolution=Resolution.DONE)
            report = rust_beads.recover_failed_closes(
                project.beads_dir,
                {
                    "run_id": "run-77",
                    "failed_at": "2026-10-26T20:00:00Z",
                    "failure_code": "hook_failed",
                    "evidence_locations": [str(tmp_path / "artifacts")],
                    "note": "STITCH FAILED: hook failed for run run-77.",
                    "actor": "agent-77",
                },
            )
            assert report["changed"] is True
            reopened = project.show(task.id)
            assert reopened.status == Status.OPEN
            assert reopened.completion_failure is not None
            assert reopened.completion_failure.run_id == "run-77"
            assert reopened.completion_failure.failure_code == "hook_failed"
            assert any(
                note.text.startswith("STITCH FAILED:") for note in reopened.notes
            )
            assert reopened.close_history[0].reopened_via is (
                ReopenCause.COMPLETION_FAILURE
            )
            assert reopened.close_history[0].close_provenance == _provenance(
                str(tmp_path / "artifacts")
            )
            # Idempotent retry records no duplicate note.
            again = rust_beads.recover_failed_closes(
                project.beads_dir,
                {
                    "run_id": "run-77",
                    "failed_at": "2026-10-26T20:01:00Z",
                    "failure_code": "hook_failed",
                    "evidence_locations": [str(tmp_path / "artifacts")],
                    "note": "STITCH FAILED: hook failed for run run-77.",
                    "actor": "agent-77",
                },
            )
            assert again["changed"] is False
            assert len(again["already_applied"]) == 1
            renoted = project.show(task.id)
            failed_notes = [
                note for note in renoted.notes if note.text.startswith("STITCH FAILED:")
            ]
            assert len(failed_notes) == 1

    def test_mirror_round_trip_preserves_close_history_provenance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # The compatibility mirror carries close-history records (with their
        # provenance) but not the flat current-close/failure facts, whose
        # schema is owned by the Rust core: the facts stay authoritative in
        # the event store and readable through the Rust facade.
        monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-77")
        monkeypatch.setenv("SASE_AGENT_NAME", "agent-77")
        monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
        with _seed_git_store(tmp_path / "store") as project:
            reopened = project.create(
                "Reopened by recovery",
                IssueType.TASK,
                task_type="bug",
                size=PhaseSize.SMALL,
                created_by="probe",
            )
            project.close([reopened.id], resolution=Resolution.DONE)
            rust_beads.recover_failed_closes(
                project.beads_dir,
                {
                    "run_id": "run-77",
                    "failed_at": "2026-10-26T20:00:00Z",
                    "failure_code": "hook_failed",
                    "evidence_locations": [str(tmp_path / "artifacts")],
                    "note": "STITCH FAILED: hook failed for run run-77.",
                    "actor": "agent-77",
                },
            )
            live_reopened = project.show(reopened.id)
            project._export()
        issues_path = tmp_path / "store" / "sdd" / "beads" / "issues.jsonl"
        assert issues_path.is_file()
        mirror = bead_db.init_db(tmp_path / "mirror.db")
        try:
            import_from_jsonl(issues_path, mirror)
            mirrored_reopened = bead_db.get_issue(mirror, reopened.id)
            assert mirrored_reopened is not None
            assert mirrored_reopened.close_history == live_reopened.close_history
            assert mirrored_reopened.close_history[0].close_provenance == _provenance(
                str(tmp_path / "artifacts")
            )
            assert mirrored_reopened.close_history[0].close_event_id
        finally:
            mirror.close()
