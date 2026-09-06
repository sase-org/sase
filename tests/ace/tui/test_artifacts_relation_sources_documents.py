"""Focused coverage for the documents Artifacts relation source."""

from __future__ import annotations

from sase.ace.tui._artifact_tab_contract import compile_provider_contract
from sase.ace.tui.relations import build_documents_relation_index
from sase.ace.tui.widgets.artifacts.bead_plan_links import BeadPlanLink
from sase.ace.tui.widgets.artifacts.plans_data_models import (
    ActivePlanDocument,
    LinkedPlanDocument,
    PlanProposal,
    PlansSnapshot,
)
from sase.bead.model import IssueType, Status
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.notifications.models import Notification


def test_documents_source_emits_lifecycle_children_and_bead_links() -> None:
    notification = Notification(
        id="p1", timestamp="2026-08-01T00:00:00+00:00", sender="planner"
    )
    link = BeadPlanLink(
        project="alpha",
        bead_id="e1",
        bead_type=IssueType.PLAN,
        bead_status=Status.IN_PROGRESS,
        bead_tier=None,
        bead_title="",
        bead_created_at="",
        reference="plan:p",
        path="/p.md",
    )
    snapshot = PlansSnapshot(
        project="alpha",
        projects=("alpha",),
        display_names={"alpha": "Alpha"},
        beads_dirs={},
        plans_roots={},
        workspace_dirs={},
        proposals=(
            PlanProposal(
                project="alpha",
                notification=notification,
                title="Plan",
                tier="epic",
                age="",
                timestamp=notification.timestamp,
                plan_path="/p.md",
                content="",
                frontmatter={},
                body="",
                agent="",
                provider_model="",
            ),
        ),
        active=(
            ActivePlanDocument(
                "alpha",
                LinkedPlanDocument(
                    reference="plan:p",
                    path="/p.md",
                    content="",
                    frontmatter={},
                    body="",
                    error=None,
                    signature=None,
                ),
                link,
            ),
        ),
        archive=(),
        bead_plan_links={("alpha", "e1"): link},
        linked_plan_documents={},
        source_key=("src",),
        errors={},
    )
    contract = compile_provider_contract(
        kind="plan",
        label="Plan",
        icon="x",
        accent="#0",
        spec=None,
        provider_spec_digest="t",
    ).contract
    index = build_documents_relation_index(snapshot, contract=contract)
    proposal = ArtifactEntryTarget("ref:plan", ("alpha", "proposal", "p1"))
    active = ArtifactEntryTarget("ref:plan", ("alpha", "active", "/p.md"))
    assert index.edges_for_relation(proposal, "children")[0].target == active
    assert index.edges_for_relation(active, "parent")[0].target == proposal
    bead = index.edges_for_relation(proposal, "beads")[0]
    assert bead.target == ArtifactEntryTarget("beads", ("alpha", "epic", "e1"))
