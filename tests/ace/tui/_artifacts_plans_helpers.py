"""Shared fixtures for the document-only Artifacts Plans pane tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.modals.inventory_project_picker import InventoryProjectChoice
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.plans_data import (
    ActivePlanDocument,
    LinkedPlanDocument,
    PlanProposal,
    PlansSnapshot,
    ProjectArchive,
)
from sase.bead.model import BeadTier, IssueType, Status
from sase.notifications.models import Notification
from sase.plan_search.model import Plan, PlanSearchMatch


def _choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(InventoryProjectChoice("alpha", "Alpha", "enabled"),),
        enabled_projects=("alpha",),
        display_names={"alpha": "Alpha"},
    )


def _all_choices() -> _ArtifactsProjectChoices:
    return _ArtifactsProjectChoices(
        choices=(
            InventoryProjectChoice("alpha", "Alpha", "enabled"),
            InventoryProjectChoice("beta", "Beta", "enabled"),
        ),
        enabled_projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
    )


def _link(
    path: Path,
    *,
    project: str = "alpha",
    bead_id: str = "alpha-1",
    status: Status = Status.IN_PROGRESS,
) -> BeadPlanLink:
    return BeadPlanLink(
        project=project,
        bead_id=bead_id,
        bead_type=IssueType.PLAN,
        bead_status=status,
        bead_tier=BeadTier.EPIC,
        bead_title="Ship the plan browser",
        bead_created_at="2026-07-01T09:00:00Z",
        reference="plan:202607/active.md",
        path=str(path),
    )


def _snapshot(tmp_path: Path) -> PlansSnapshot:
    proposal_path = tmp_path / "proposal.md"
    proposal_body = "# Ship the plan browser\n\nPending proposal body."
    notification = Notification(
        id="proposal-1",
        timestamp="2026-07-06T11:58:00+00:00",
        sender="planner",
        files=[str(proposal_path)],
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
        plan_path=str(proposal_path),
        content=proposal_body,
        frontmatter={"title": "Ship the plan browser", "tier": "epic"},
        body=proposal_body,
        agent="alpha.plan",
        provider_model="codex/gpt-5",
    )
    active_path = tmp_path / "202607" / "active.md"
    link = _link(active_path)
    document = LinkedPlanDocument(
        reference=link.reference,
        path=str(active_path),
        content="---\ntitle: Active rollout\ntier: epic\nstatus: wip\n---\nActive body.",
        frontmatter={
            "title": "Active rollout",
            "tier": "epic",
            "status": "wip",
            "create_time": "2026-07-05 10:00:00",
        },
        body="Active body.",
        error=None,
        signature=(1, 2, 3, 4),
    )
    archived_path = tmp_path / "202607" / "archive.md"
    archive_match = PlanSearchMatch(
        plan=Plan(
            source="repo",
            kind="epic",
            path=str(archived_path),
            relpath="202607/archive.md",
            name="archive",
            title="Archived rollout",
            status="done",
            created_at="2026-07-04 10:00:00",
            prompt_link="",
            summary="Archived summary.",
            body="Archived body.",
            frontmatter={"tier": "epic", "status": "done"},
        ),
        matched_fields=[],
        score=1.0,
    )
    closed_link = replace(
        link,
        bead_id="alpha-closed",
        bead_status=Status.CLOSED,
        reference="plan:202607/archive.md",
        path=str(archived_path),
    )
    return PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={"alpha": str(tmp_path / "beads")},
        plans_roots={"alpha": {"plans": str(tmp_path)}},
        workspace_dirs={"alpha": str(tmp_path / "workspace")},
        proposals=(proposal,),
        active=(ActivePlanDocument("alpha", document, link),),
        archive=(ProjectArchive("alpha", archive_match),),
        bead_plan_links={
            ("alpha", link.bead_id): link,
            ("alpha", closed_link.bead_id): closed_link,
        },
        linked_plan_documents={("alpha", link.bead_id): document},
        source_key=("fixture",),
        errors={},
    )


def _all_projects_snapshot(tmp_path: Path) -> PlansSnapshot:
    snapshot = _snapshot(tmp_path)
    proposal = replace(snapshot.proposals[0], project="beta")
    active = snapshot.active[0]
    owner = replace(active.owner, project="beta")
    active = replace(active, project="beta", owner=owner)
    archive = replace(snapshot.archive[0], project="beta")
    links = {
        ("beta", bead_id): replace(link, project="beta")
        for (_project, bead_id), link in snapshot.bead_plan_links.items()
    }
    return replace(
        snapshot,
        project=None,
        projects=("alpha", "beta"),
        display_names={"alpha": "Alpha", "beta": "Beta"},
        proposals=(proposal,),
        active=(active,),
        archive=(archive,),
        bead_plan_links=links,
    )
