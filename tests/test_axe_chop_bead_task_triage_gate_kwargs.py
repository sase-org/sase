"""Gate-factory signature regression for bead_task_triage create_gate."""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

from sase.bead.flag_gate import FLAG_TRIAGE_KIND, create_flag_triage_gate
from sase.bead.model import CloseRecord, ReopenCause
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND, create_bead_snooze_gate
from sase.bead.task_gate import TASK_TRIAGE_KIND, create_task_triage_gate
from sase.scripts._bead_task_triage_gates import create_gate

from tests._axe_chop_bead_task_triage_helpers import (
    flag_task_fields,
    make_due_flag,
    make_snoozed_task,
    make_task,
)


def _reopened_issue() -> Any:
    issue = make_snoozed_task()
    issue.closed_at = "2026-09-01T00:00:00+00:00"
    issue.close_history = [
        CloseRecord(
            closed_at="2026-09-01T00:00:00+00:00",
            reopened_at="2026-09-02T00:00:00+00:00",
            reopened_via=ReopenCause.OPEN,
        )
    ]
    return issue


def test_task_triage_factory_receives_closed_at() -> None:
    issue = make_task()
    issue.closed_at = "2026-09-01T00:00:00+00:00"
    issue.close_history = [
        CloseRecord(
            closed_at="2026-09-01T00:00:00+00:00",
            reopened_at="2026-09-02T00:00:00+00:00",
            reopened_via=ReopenCause.OPEN,
        )
    ]
    task_factory = create_autospec(create_task_triage_gate)
    snooze_factory = create_autospec(create_bead_snooze_gate)
    flag_factory = create_autospec(create_flag_triage_gate)

    create_gate(
        TASK_TRIAGE_KIND,
        request_id="bead-task-triage-x",
        bead_id=issue.id,
        project_name="sase",
        issue=issue,
        task_gate_factory=task_factory,
        snooze_gate_factory=snooze_factory,
        flag_gate_factory=flag_factory,
    )

    assert task_factory.call_count == 1
    assert task_factory.call_args.kwargs["closed_at"] == issue.closed_at


def test_snooze_factory_does_not_receive_closed_at() -> None:
    issue = _reopened_issue()
    assert issue.snooze is not None
    task_factory = create_autospec(create_task_triage_gate)
    snooze_factory = create_autospec(create_bead_snooze_gate)
    flag_factory = create_autospec(create_flag_triage_gate)

    create_gate(
        BEAD_SNOOZE_KIND,
        request_id="bead-snooze-x",
        bead_id=issue.id,
        project_name="sase",
        issue=issue,
        task_gate_factory=task_factory,
        snooze_gate_factory=snooze_factory,
        flag_gate_factory=flag_factory,
    )

    assert snooze_factory.call_count == 1
    assert "closed_at" not in snooze_factory.call_args.kwargs
    assert snooze_factory.call_args.kwargs["snooze"] == issue.snooze


def test_flag_factory_receives_no_closed_at() -> None:
    issue = make_due_flag()
    issue.task_type_fields = flag_task_fields()
    task_factory = create_autospec(create_task_triage_gate)
    snooze_factory = create_autospec(create_bead_snooze_gate)
    flag_factory = create_autospec(create_flag_triage_gate)

    create_gate(
        FLAG_TRIAGE_KIND,
        request_id="bead-flag-triage-x",
        bead_id=issue.id,
        project_name="sase",
        issue=issue,
        task_gate_factory=task_factory,
        snooze_gate_factory=snooze_factory,
        flag_gate_factory=flag_factory,
    )

    assert flag_factory.call_count == 1
