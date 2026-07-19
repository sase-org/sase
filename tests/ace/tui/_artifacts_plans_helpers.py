"""Shared fixtures for Artifacts Plans pane tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts.plans_data import (
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
    ProjectIssue,
)
from sase.bead.model import BeadTier, Dependency, Issue, IssueType, Status
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch


def _choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
        ),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha"},
    )


def _all_choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice(
                project_key="alpha",
                display_name="Alpha",
                state="enabled",
            ),
            InventoryProjectChoice(
                project_key="beta",
                display_name="Beta",
                state="enabled",
            ),
        ),
        enabled_projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
    )


def _snapshot(tmp_path: Path) -> PlansSnapshot:
    proposal_frontmatter = {
        "title": "Ship the plan browser",
        "tier": "epic",
        "status": "wip",
        "create_time": "2026-07-06 11:58:00",
        "goal": "Make plans readable and actionable across every enabled project.",
        "reviewer": "platform-ui",
    }
    proposal_body = (
        "# Ship the plan browser\n\n"
        "Aggregate every enabled project while keeping `inline code` readable."
    )
    notification = Notification(
        id="proposal-1",
        timestamp="2026-07-06T11:58:00+00:00",
        sender="planner",
        files=[str(tmp_path / "proposal.md")],
        action="PlanApproval",
        action_data={"response_dir": str(tmp_path / "approval")},
    )
    proposal = PlanProposal(
        project="alpha",
        notification=notification,
        title="Ship the plan browser",
        tier="epic",
        age="2m ago",
        timestamp=notification.timestamp,
        plan_path=notification.files[0],
        content=(
            "---\n"
            "title: Ship the plan browser\n"
            "tier: epic\n"
            "status: wip\n"
            "create_time: 2026-07-06 11:58:00\n"
            "goal: Make plans readable and actionable across every enabled project.\n"
            "reviewer: platform-ui\n"
            "---\n"
            f"{proposal_body}"
        ),
        frontmatter=proposal_frontmatter,
        body=proposal_body,
        agent="alpha.plan",
        provider_model="codex/gpt-5",
    )
    epic = Issue(
        id="alpha-1",
        title="Artifacts plans with a deliberately long title that stays on one line",
        status=Status.OPEN,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        description="Build the Plans pane.",
        changespec_name="alpha-cl",
        changespec_bug_id="42",
        created_at="2026-06-30T12:00:00Z",
        updated_at="2026-07-05T15:30:00Z",
    )
    first = Issue(
        id="alpha-1.1",
        title="Load plans",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        model="codex/gpt-5",
        created_at="2026-07-01T09:00:00Z",
        updated_at="2026-07-05T10:00:00Z",
    )
    second = Issue(
        id="alpha-1.2",
        title="Render dependency state",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
        dependencies=[
            Dependency(
                issue_id="alpha-1.2",
                depends_on_id="alpha-1.1",
                created_at="2026-07-02T09:00:00Z",
            )
        ],
        created_at="2026-07-02T09:00:00Z",
        updated_at="2026-07-05T11:00:00Z",
    )
    archive = PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(tmp_path / "202607" / "archive.md"),
            relpath="202607/archive.md",
            name="archive",
            title="Archived rollout",
            status="done",
            created_at="2026-07-04 10:00:00",
            prompt_link="",
            summary="The archived plan summary.",
            body="# Rollout\n\nDone.",
            frontmatter={
                "title": "Archived rollout",
                "tier": "epic",
                "status": "done",
                "create_time": "2026-07-04 10:00:00",
                "goal": "Record a completed rollout with its full plan metadata.",
            },
        ),
        matched_fields=[],
        score=1.0,
    )
    return PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={"alpha": str(tmp_path / "beads")},
        plans_roots={"alpha": str(tmp_path)},
        workspace_dirs={"alpha": str(tmp_path / "workspace")},
        proposals=(proposal,),
        epics=(ProjectIssue("alpha", epic),),
        phases_by_epic={
            ("alpha", epic.id): (
                ProjectIssue("alpha", first),
                ProjectIssue("alpha", second),
            )
        },
        ready_ids=frozenset({("alpha", epic.id), ("alpha", first.id)}),
        blocked_ids=frozenset({("alpha", second.id)}),
        archive=(ProjectArchive("alpha", archive),),
        linked_plan_documents={},
        source_key=("fixture",),
        errors={},
    )


def _all_projects_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _snapshot(tmp_path)
    proposal = replace(snapshot.proposals[0], project="beta")
    epic = snapshot.epics[0].issue
    phases = tuple(
        ProjectIssue("beta", entry.issue)
        for entry in snapshot.phases_by_epic[("alpha", epic.id)]
    )
    archive = ProjectArchive("beta", snapshot.archive[0].match)
    return replace(
        snapshot,
        project=None,
        projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
        beads_dirs={
            "alpha": str(tmp_path / "alpha" / "beads"),
            "beta": str(tmp_path / "beta" / "beads"),
        },
        plans_roots={
            "alpha": str(tmp_path / "alpha"),
            "beta": str(tmp_path / "beta"),
        },
        workspace_dirs={
            "alpha": str(tmp_path / "alpha-workspace"),
            "beta": str(tmp_path / "beta-workspace"),
        },
        proposals=(proposal,),
        epics=(ProjectIssue("beta", epic),),
        phases_by_epic={("beta", epic.id): phases},
        ready_ids=frozenset(
            {
                ("beta", epic.id),
                ("beta", phases[0].issue.id),
            }
        ),
        blocked_ids=frozenset({("beta", phases[1].issue.id)}),
        archive=(archive,),
    )
