"""Pending TaskTriage lookup and cancellation coverage."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.bead._task_gate_actions import _find_pending_task_triage
from sase.bead.task_gate import (
    cancel_task_triage,
    create_task_triage_gate,
)
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.notification_gates.durability import atomic_write_json
from sase.notification_gates.models import GateError


def _gate(request_id: str, *, project: str = "sase", bead_id: str = "sase-a1"):
    return create_task_triage_gate(
        request_id=request_id,
        bead_id=bead_id,
        project=project,
        title="Triage me",
    )


def test_find_pending_task_triage_matches_payload_and_skips_terminal_bundles(
    gate_home: Path,
) -> None:
    del gate_home
    answered = _gate("answered", bead_id="sase-answered")
    atomic_write_json(answered.bundle_path / "response.json", {})
    _gate("canceled", bead_id="sase-canceled")
    assert cancel_task_triage("sase", "sase-canceled", reason="no_longer_needed")
    _gate("other-project", project="other", bead_id="sase-a1")
    _gate("pending", bead_id="sase-a1")

    assert _find_pending_task_triage("sase", "sase-a1") == "pending"
    assert _find_pending_task_triage("sase", "sase-answered") is None
    assert _find_pending_task_triage("sase", "sase-canceled") is None
    assert _find_pending_task_triage("missing", "sase-a1") is None


def test_cancel_task_triage_settles_gate_and_is_idempotent(gate_home: Path) -> None:
    del gate_home
    gate = _gate("pending-cancel")

    assert cancel_task_triage("sase", "sase-a1", reason="closed_from_ace", source="ace")
    assert (gate.bundle_path / "cancellation.json").is_file()
    assert _find_pending_task_triage("sase", "sase-a1") is None
    assert not cancel_task_triage("sase", "sase-a1", reason="closed_from_ace")


def test_cancel_task_triage_treats_already_answered_as_benign(
    gate_home: Path,
) -> None:
    del gate_home
    _gate("answered-race")
    error = GateError("already_answered", "response.json", "already answered")
    with patch("sase.notification_gates.executor.cancel_gate", side_effect=error):
        assert not cancel_task_triage("sase", "sase-a1", reason="race")


def test_close_ready_task_persists_close_and_cancels_pending_gate(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        task = project.create(
            "Ready task", IssueType.TASK, task_type="bug", size="small"
        )
        project.update(task.id, status=Status.READY.value)
    gate = _gate("close-integration", bead_id=task.id)

    with BeadProject(project_dir) as project:
        project.close(
            [task.id],
            reason="Completed in ACE",
            resolution="done",
        )
    assert cancel_task_triage("sase", task.id, reason="closed_from_ace", source="ace")

    with BeadProject(project_dir) as project:
        closed = project.show(task.id)
    assert closed.status is Status.CLOSED
    assert closed.close_reason == "Completed in ACE"
    assert (gate.bundle_path / "cancellation.json").is_file()
