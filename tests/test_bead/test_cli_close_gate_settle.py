"""CLI coverage for close_settle: closing a task bead settles its gate.

``sase bead close`` cancels a just-closed task bead's pending TaskTriage or
BeadSnooze gate right after the store mutation commits, so ACE's inotify
watch over ``~/.sase/notifications`` refreshes immediately instead of waiting
up to five minutes for the reconciler's next tick.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, SnoozeRecord, Status
from sase.bead.project import BeadProject
from sase.bead.snooze_gate import create_bead_snooze_gate
from sase.bead.task_gate import create_task_triage_gate
from sase.main.parser import create_parser
from sase.notification_gates.models import GateError

_PROJECT = "sase"


@pytest.fixture(autouse=True)
def _fixed_project_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the close command's project resolution to match the test gates."""
    monkeypatch.setattr(
        "sase.bead.project_name.infer_project_name_from_cwd", lambda: _PROJECT
    )


def _close_args(*ids: str, reason: str = "done"):
    return create_parser().parse_args(["bead", "close", *ids, "--reason", reason])


def _ready_task(project: BeadProject, title: str):
    task = project.create(title, IssueType.TASK, size="small")
    project.update(task.id, status=Status.READY.value)
    return task


def test_close_ready_task_cancels_its_task_triage_gate(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        task = _ready_task(project, "Ready task")
    gate = create_task_triage_gate(
        request_id="triage-close-settle",
        bead_id=task.id,
        project=_PROJECT,
        title=task.title,
    )

    bead_cli.handle_bead_close(_close_args(task.id))

    assert (gate.bundle_path / "cancellation.json").is_file()


def test_close_snoozed_task_cancels_its_bead_snooze_gate(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        task = _ready_task(project, "Snoozed task")
        project.snooze(
            task.id,
            until="2026-09-01T00:00:00Z",
            actor="tester",
            reason="waiting on upstream",
        )
    gate = create_bead_snooze_gate(
        request_id="snooze-close-settle",
        bead_id=task.id,
        project=_PROJECT,
        title=task.title,
        snooze=SnoozeRecord(
            until="2026-09-01T00:00:00Z",
            snoozed_at="2026-08-01T00:00:00Z",
            snoozed_by="tester",
            reason="waiting on upstream",
        ),
    )

    bead_cli.handle_bead_close(_close_args(task.id))

    assert (gate.bundle_path / "cancellation.json").is_file()


def test_close_task_with_no_gate_is_a_clean_noop(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        task = _ready_task(project, "Lonely task")

    bead_cli.handle_bead_close(_close_args(task.id))

    with BeadProject(project_dir) as project:
        closed = project.show(task.id)
    assert closed.status is Status.CLOSED


def test_close_of_plan_performs_no_gate_scan(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        plan = project.create("Plan bead", IssueType.PLAN)
    scan = MagicMock()

    with patch("sase.bead.close_gate_settle.find_pending_bead_gates", scan):
        bead_cli.handle_bead_close(_close_args(plan.id))

    scan.assert_not_called()


def test_multi_bead_close_performs_exactly_one_gate_scan(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        first = _ready_task(project, "First ready task")
        second = _ready_task(project, "Second ready task")
    first_gate = create_task_triage_gate(
        request_id="triage-first",
        bead_id=first.id,
        project=_PROJECT,
        title=first.title,
    )
    second_gate = create_task_triage_gate(
        request_id="triage-second",
        bead_id=second.id,
        project=_PROJECT,
        title=second.title,
    )
    from sase.bead.gate_lookup import find_pending_bead_gates as real_scan

    scan = MagicMock(wraps=real_scan)
    with patch("sase.bead.close_gate_settle.find_pending_bead_gates", scan):
        bead_cli.handle_bead_close(_close_args(first.id, second.id))

    assert scan.call_count == 1
    assert (first_gate.bundle_path / "cancellation.json").is_file()
    assert (second_gate.bundle_path / "cancellation.json").is_file()


def test_close_settle_treats_already_answered_gate_as_benign(
    project_dir: Path,
    gate_home: Path,
) -> None:
    del gate_home
    with BeadProject(project_dir) as project:
        task = _ready_task(project, "Raced task")
    create_task_triage_gate(
        request_id="triage-race",
        bead_id=task.id,
        project=_PROJECT,
        title=task.title,
    )
    error = GateError("already_answered", "response.json", "already answered")

    with patch("sase.notification_gates.executor.cancel_gate", side_effect=error):
        bead_cli.handle_bead_close(_close_args(task.id))

    with BeadProject(project_dir) as project:
        closed = project.show(task.id)
    assert closed.status is Status.CLOSED
