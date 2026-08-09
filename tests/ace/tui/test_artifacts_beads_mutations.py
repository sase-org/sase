"""Focused mutation contracts for the Artifacts Beads pane."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.artifacts_beads import (
    ArtifactsBeadsActionsMixin,
    _next_bead_status,
    _unclosed_descendant_ids,
)
from sase.ace.tui.modals.bead_editor_modal import BeadEditorResult
from sase.ace.tui.widgets.artifacts.beads_data_models import (
    BeadsSnapshot,
    ProjectBead,
)
from sase.ace.tui.widgets.artifacts.beads_list import BeadRow
from sase.bead.model import BeadTier, Issue, IssueType, PhaseSize, Status


@pytest.mark.parametrize(
    ("issue_type", "status", "expected"),
    [
        (IssueType.TASK, Status.OPEN, Status.READY),
        (IssueType.TASK, Status.CLAIMED, Status.READY),
        (IssueType.TASK, Status.READY, Status.IN_PROGRESS),
        # Nothing cycles *into* snoozed -- a snooze needs a wake time -- but
        # cycling out of it must return the task to triage.
        (IssueType.TASK, Status.SNOOZED, Status.READY),
        (IssueType.TASK, Status.IN_PROGRESS, Status.CLOSED),
        (IssueType.PHASE, Status.OPEN, Status.IN_PROGRESS),
        (IssueType.PLAN, Status.CLOSED, Status.OPEN),
    ],
)
def test_status_cycle_is_type_aware(
    issue_type: IssueType, status: Status, expected: Status
) -> None:
    issue = Issue(
        "sase-a1",
        "Work",
        issue_type=issue_type,
        status=status,
        parent_id="sase-epic" if issue_type is IssueType.PHASE else None,
    )

    assert _next_bead_status(issue) is expected


def test_editor_result_submits_only_changed_type_valid_fields() -> None:
    issue = Issue(
        "sase-a1",
        "Old",
        issue_type=IssueType.TASK,
        description="same",
        notes="notes",
        size=PhaseSize.SMALL,
    )
    result = BeadEditorResult(
        title="New",
        description="same",
        notes="notes",
        status="ready",
        assignee="",
        owner="",
        model="",
        size="medium",
        design="",
        patch_name="must-not-submit",
        patch_bug_id="99",
    )

    assert result.changed_fields(issue) == {
        "title": "New",
        "status": "ready",
        "size": "medium",
    }


def test_descendant_preview_lists_every_unclosed_descendant_once() -> None:
    epic = Issue(
        "sase-epic",
        "Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = Issue(
        "sase-epic.1",
        "Phase",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
    )
    closed_phase = replace(
        phase,
        id="sase-epic.2",
        status=Status.CLOSED,
    )
    snapshot = BeadsSnapshot(
        project="sase",
        projects=("sase",),
        display_names={"sase": "sase"},
        beads_dirs={"sase": "/tmp/beads"},
        workspace_dirs={"sase": "/tmp/workspace"},
        tasks=(),
        epics=(ProjectBead("sase", epic),),
        phases_by_epic={
            ("sase", epic.id): (
                ProjectBead("sase", phase),
                ProjectBead("sase", closed_phase),
            )
        },
        ready_ids=frozenset(),
        blocked_ids=frozenset(),
        plan_links={},
        triage_gates={},
        source_key=(),
        errors={},
    )
    row = BeadRow("epic", "epic:sase-epic", "sase", epic)

    assert _unclosed_descendant_ids(row, snapshot) == (phase.id,)


def test_tracked_submission_uses_operation_scoped_dedup_key() -> None:
    submit = Mock(return_value=SimpleNamespace(task_id="task-1"))
    refresh = Mock()
    host = SimpleNamespace(_submit_tracked_task=submit)
    pane = SimpleNamespace(request_refresh=refresh)
    task = Mock()

    ArtifactsBeadsActionsMixin._submit_beads_task(
        host,
        pane,
        project="sase",
        bead_id="sase-a1",
        operation="note",
        display_name="Add note · sase-a1",
        workspace="/work/sase",
        task=task,
    )

    assert submit.call_args.args[:4] == (
        "bead-note",
        "sase-a1",
        "/work/sase",
        task,
    )
    assert submit.call_args.kwargs["dedup_key"] == "beads:note:sase:sase-a1"
