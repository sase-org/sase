"""Indexed bead detail resolution coverage."""

from __future__ import annotations

from sase.bead.cli_detail import IssueDetailIndex
from sase.bead.model import BeadTier, Dependency, Issue, IssueType


def test_issue_detail_index_resolves_relationships_and_parent_plan() -> None:
    root = Issue(
        "sase-ai",
        "Epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        design="plans:202607/bead_pages.md",
    )
    dependency = Issue(
        "sase-dep",
        "Dependency",
        issue_type=IssueType.PLAN,
        tier=BeadTier.PLAN,
    )
    phase = Issue(
        "sase-ai.10",
        "Phase",
        parent_id=root.id,
        dependencies=[Dependency("sase-ai.10", dependency.id, "2026-07-28T00:00:00Z")],
    )
    blocker = Issue(
        "sase-ai.11",
        "Blocker",
        parent_id=root.id,
        dependencies=[Dependency("sase-ai.11", phase.id, "2026-07-28T00:00:00Z")],
    )

    detail = IssueDetailIndex.from_issues((root, dependency, phase, blocker)).resolve(
        phase
    )

    assert [ref.issue_id for ref in detail.ancestors] == [root.id]
    assert [ref.issue_id for ref in detail.depends_on] == [dependency.id]
    assert [ref.issue_id for ref in detail.blocks] == [blocker.id]
    assert detail.plan is not None
    assert detail.plan.source == "parent"
    assert detail.plan.path == root.design
    assert detail.plan.from_ref is not None
    assert detail.plan.from_ref.issue_id == root.id
