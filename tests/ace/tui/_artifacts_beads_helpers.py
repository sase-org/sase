"""Shared fixtures for Artifacts Beads pane tests."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.widgets.artifacts.beads_data import (
    BeadsSnapshot,
    PendingTriage,
    ProjectBead,
)
from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Status,
)


def snapshot(tmp_path: Path, *, project: str | None = "alpha") -> BeadsSnapshot:
    ready_task = Issue(
        id="alpha-ready",
        title="Ready for triage",
        status=Status.READY,
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        description="Decide whether this task should launch.",
        created_at="2026-07-03T09:00:00Z",
        updated_at="2026-07-06T12:00:00Z",
    )
    open_task = Issue(
        id="alpha-open",
        title="Ordinary follow-up",
        issue_type=IssueType.TASK,
        size=PhaseSize.MEDIUM,
        created_at="2026-07-04T09:00:00Z",
        updated_at="2026-07-05T12:00:00Z",
    )
    epic = Issue(
        id="alpha-1",
        title="Build bead browsing",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202608/beads.md",
        owner="owner@example.com",
        assignee="alpha.agent",
        created_at="2026-07-01T09:00:00Z",
        updated_at="2026-07-06T10:00:00Z",
    )
    first = Issue(
        id="alpha-1.1",
        title="Load the snapshot",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        status=Status.CLOSED,
        size=PhaseSize.SMALL,
        created_at="2026-07-01T10:00:00Z",
        updated_at="2026-07-05T10:00:00Z",
    )
    second = Issue(
        id="alpha-1.2",
        title="Render the tree",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        size=PhaseSize.MEDIUM,
        dependencies=[
            Dependency(
                issue_id="alpha-1.2",
                depends_on_id=first.id,
                created_at="2026-07-02T10:00:00Z",
            )
        ],
        created_at="2026-07-02T10:00:00Z",
        updated_at="2026-07-06T11:00:00Z",
    )
    return BeadsSnapshot(
        project=project,
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={"alpha": str(tmp_path / "beads")},
        workspace_dirs={"alpha": str(tmp_path / "workspace")},
        tasks=(ProjectBead("alpha", ready_task), ProjectBead("alpha", open_task)),
        epics=(ProjectBead("alpha", epic),),
        phases_by_epic={
            ("alpha", epic.id): (
                ProjectBead("alpha", first),
                ProjectBead("alpha", second),
            )
        },
        ready_ids=frozenset({("alpha", epic.id), ("alpha", second.id)}),
        blocked_ids=frozenset(),
        plan_links={("alpha", epic.id): str(tmp_path / "beads.md")},
        triage_gates={
            ("alpha", ready_task.id): PendingTriage(
                notification_id="notification-1",
                request_id="task-triage-alpha-ready",
                created_at="2026-07-06T12:00:00Z",
            )
        },
        source_key=("fixture",),
        errors={},
    )


__all__ = ["snapshot"]
