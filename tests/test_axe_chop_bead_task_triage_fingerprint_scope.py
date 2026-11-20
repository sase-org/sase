"""The triage presentation fingerprint covers only what the bead's gate renders."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import sase.scripts.sase_chop_bead_task_triage as task_triage
from sase.bead.model import (
    CloseRecord,
    Issue,
    ReopenCause,
    Resolution,
    TaskPlusOneEvidence,
)
from tests._axe_chop_bead_task_triage_helpers import (
    make_due_flag,
    make_runtime,
    make_snoozed_task,
    make_task,
    patch_project,
)


def _evidence(reporter: str = "bryan") -> TaskPlusOneEvidence:
    return TaskPlusOneEvidence(
        timestamp="2026-01-02T00:00:00Z", reporter=reporter, note="Seen again."
    )


def _close_record() -> CloseRecord:
    return CloseRecord(
        closed_at="2026-01-01T00:00:00Z",
        reopened_at="2026-01-02T00:00:00Z",
        reopened_via=ReopenCause.OPEN,
        close_reason="Looked fixed.",
        resolution=Resolution.DONE,
    )


def _track_current_gate(tmp_path: Path, issue: Issue, kind: str) -> None:
    request_id = task_triage._request_id("sase", issue.id, 1, kind)
    task_triage._write_state(
        tmp_path / task_triage._STATE_FILENAME,
        {
            "sase": task_triage._ProjectState(
                gates={issue.id: request_id},
                generations={issue.id: 1},
                fingerprints={issue.id: task_triage._presentation_fingerprint(issue)},
                kinds={issue.id: kind},
            )
        },
    )


def test_edits_to_non_rendered_fields_cause_no_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = make_task()
    patch_project(monkeypatch, tmp_path, [task])
    _track_current_gate(tmp_path, task, task_triage.TASK_TRIAGE_KIND)
    monkeypatch.setattr(task_triage, "_gate_state", lambda _kind, _id: "pending")
    for name in ("_cancel_pending_gate", "_retire_superseded_gate", "_create_gate"):
        monkeypatch.setattr(
            task_triage,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(f"{_name} was called"),
        )

    edits = (
        ("owner", "bryan"),
        ("assignee", "sase-task.1"),
        ("updated_at", "2026-01-03T00:00:00Z"),
        ("parent_id", "sase-epic"),
        ("owner", "someone-else"),
    )
    for field_name, value in edits:
        setattr(task, field_name, value)
        result = task_triage._run(make_runtime(tmp_path))
        assert result.counters["skipped"] == 1
        assert result.counters["canceled"] == 0


def test_flag_gate_fingerprint_ignores_evidence_and_close_history() -> None:
    flag = make_due_flag()
    before = task_triage._presentation_fingerprint(flag)

    flag.plus_one_evidence = [_evidence()]
    flag.close_history = [_close_record()]

    assert task_triage._presentation_fingerprint(flag) == before


@pytest.mark.parametrize("make_issue", [make_task, make_snoozed_task])
def test_triage_and_wake_fingerprints_track_evidence_and_close_history(
    make_issue: Callable[[], Issue],
) -> None:
    issue = make_issue()
    before = task_triage._presentation_fingerprint(issue)

    issue.plus_one_evidence = [_evidence()]
    with_evidence = task_triage._presentation_fingerprint(issue)
    issue.close_history = [_close_record()]

    assert with_evidence != before
    assert task_triage._presentation_fingerprint(issue) != with_evidence
