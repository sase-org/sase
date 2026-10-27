"""Close-plus-failure regressions for failed-close recovery.

Split from ``tests.test_finalizers_failed_close_recovery``; the original
module re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.failed_close_recovery import (
    RECOVERY_OUTCOME_FILENAME,
    RECOVERY_REQUEST_FILENAME,
    STITCH_FAILED_NOTE_PREFIX,
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
    "TestClosePlusBeforeCommitFailure",
    "TestClosePlusDeclarationRecoveryFailure",
]


def _recovery_journal_events(artifacts: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    journal = artifacts / "finalizers" / "progress.jsonl"
    if not journal.is_file():
        return events
    for line in journal.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("event") == "failed_close_recovery":
            events.append(record)
    return events


class TestClosePlusBeforeCommitFailure:
    def test_recovery_reopens_close(
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
            plan_id, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
                run_controller(artifacts)
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None
            assert phase.completion_failure.run_id == "run-1"
            assert phase.completion_failure.failure_code == "stitch_failed"
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            text = failed_notes[0].text
            assert "run-1" in text
            assert "hook failed" in text
            ancestors = project.show(plan_id)
            assert ancestors.status == Status.OPEN

    def test_request_and_outcome_artifacts_persisted(
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
            close_phase_with_plan(project)
            beads_dir = project.beads_dir
        with machine_lane(monkeypatch, beads_dir):
            submit_commit(artifacts)
            with pytest.raises(BuiltinCommitFinalizerError):
                run_controller(artifacts)
        request = json.loads(
            (artifacts / RECOVERY_REQUEST_FILENAME).read_text(encoding="utf-8")
        )
        assert request["run_id"] == "run-1"
        assert request["failure_code"] == "stitch_failed"
        assert request["note"].startswith(STITCH_FAILED_NOTE_PREFIX)
        outcome = json.loads(
            (artifacts / RECOVERY_OUTCOME_FILENAME).read_text(encoding="utf-8")
        )
        assert outcome["attempted"] is True
        assert outcome["published"] is True
        assert outcome["publication_error"] == ""
        events = _recovery_journal_events(artifacts)
        assert len(events) == 1
        assert events[0]["published"] is True


class TestClosePlusDeclarationRecoveryFailure:
    def test_recovery_names_missing_stitch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        artifacts = tmp_path / "artifacts"
        prepare_commit_run(monkeypatch, artifacts, repo)
        resolve_and_persist_finalizer_plan(
            PromptDirectives(), artifacts_dir=str(artifacts)
        )
        with seed_git_store(tmp_path / "beadstore") as project:
            _, phase_id = close_phase_with_plan(project)
            beads_dir = project.beads_dir

        def silent_provider(prompt: str, **_kwargs: object) -> InvokeResult:
            return InvokeResult(content="no declaration here")

        provider = MagicMock()
        provider.invoke.side_effect = silent_provider
        with machine_lane(monkeypatch, beads_dir):
            with pytest.raises(RuntimeError, match="declaration recovery failed"):
                run_controller(artifacts, provider)
        with BeadProject(tmp_path / "beadstore") as project:
            phase = project.show(phase_id)
            assert phase.status == Status.OPEN
            assert phase.completion_failure is not None
            assert phase.completion_failure.run_id == "run-1"
            failed_notes = [
                note
                for note in phase.notes
                if note.text.startswith(STITCH_FAILED_NOTE_PREFIX)
            ]
            assert len(failed_notes) == 1
            assert "No stitch/message file was created" in failed_notes[0].text
            assert "declaration recovery failed" in failed_notes[0].text.lower()
