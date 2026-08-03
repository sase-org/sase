"""Indexed bead detail resolution coverage."""

from __future__ import annotations

from typing import cast

from sase.bead.cli_detail import IssueDetailIndex, resolve_issue_detail
from sase.bead.model import BeadTier, Dependency, Issue, IssueType
from sase.bead.project import BeadProject
from sase.core.bead_read_facade import BeadIssueDetailSnapshot


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


def test_resolve_issue_detail_consumes_single_read_snapshot() -> None:
    issue = Issue(
        "sase-ai.1",
        "Phase",
        parent_id="missing-parent",
        dependencies=[
            Dependency("sase-ai.1", "missing-dependency", "2026-08-03T00:00:00Z")
        ],
    )
    phase = Issue("sase-ai.1.1", "Child phase", parent_id=issue.id)
    child_epic = Issue(
        "sase-child",
        "Child epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        parent_id=issue.id,
    )
    blocker = Issue(
        "sase-blocker",
        "Blocker",
        dependencies=[Dependency("sase-blocker", issue.id, "2026-08-03T00:00:00Z")],
    )
    snapshot = BeadIssueDetailSnapshot(
        issue=issue,
        ancestors=(None,),
        children=(phase, child_epic),
        depends_on=(None,),
        blocks=(blocker,),
    )

    class SnapshotView:
        def show_issue_detail(self, issue_id: str) -> BeadIssueDetailSnapshot:
            assert issue_id == issue.id
            return snapshot

    detail = resolve_issue_detail(cast(BeadProject, SnapshotView()), issue.id)

    assert [ref.issue_id for ref in detail.ancestors] == ["missing-parent"]
    assert [ref.issue_id for ref in detail.phases] == [phase.id]
    assert [ref.issue_id for ref in detail.child_epics] == [child_epic.id]
    assert [ref.issue_id for ref in detail.depends_on] == ["missing-dependency"]
    assert [ref.issue_id for ref in detail.blocks] == [blocker.id]
