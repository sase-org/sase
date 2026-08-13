"""Shared fixtures and link resolvers for bead page rendering tests."""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import cast

from sase.bead.model import (
    BeadTier,
    Dependency,
    Issue,
    IssueType,
    PhaseSize,
    Resolution,
    Status,
)
from sase.bead.project import BeadProject
from sase.bead_pages.associations import (
    BeadAgentAssociation,
    BeadAssociationIndex,
    BeadAssociations,
    BeadCommitAssociation,
    BeadCommitRepository,
)
from sase.bead_pages.rendering import render_bead_page

GOLDEN_DIR = Path(__file__).parent / "golden" / "bead_pages"
CREATOR = "alice.athena.sase-ai.plan"
CREATOR_URL = (
    "https://github.com/sase-org/sase--agents/blob/main/agents/"
    "alice.athena.sase-ai.plan/README.md"
)


class View:
    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self._issues = {issue.id: issue for issue in issues}

    def show(self, issue_id: str) -> Issue:
        return self._issues[issue_id]

    def list_issues(self) -> list[Issue]:
        return list(self._issues.values())

    def get_epic_children(self, issue_id: str) -> list[Issue]:
        return [issue for issue in self._issues.values() if issue.parent_id == issue_id]


class Links:
    def plan_url(self, plan_ref: str) -> str | None:
        assert plan_ref == "plan:202607/bead_pages.md"
        return "https://github.com/sase-org/sase--plans/blob/main/202607/bead_pages.md"

    def agent_url(self, agent_name: str) -> str | None:
        assert agent_name == CREATOR
        return CREATOR_URL


class ReferenceLinks:
    """A resolver with every hosted-link capability the page renderer uses."""

    def plan_url(self, plan_ref: str) -> str | None:
        return f"https://example.test/plans/{plan_ref.removeprefix('plan:')}"

    def bead_url(self, bead_id: str) -> str | None:
        return f"https://example.test/beads/{bead_id}.md"

    def agent_url(self, agent_name: str) -> str | None:
        return None

    def commit_url(self, sha: str) -> str | None:
        return f"https://example.test/commit/{sha}"


def fixtures() -> tuple[View, Issue, Issue, BeadAssociationIndex]:
    root = Issue(
        "sase-ai",
        "Published bead pages",
        status=Status.CLOSED,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        owner="owner@example.com",
        assignee="alice.athena.sase-ai.land",
        created_at="2026-07-28T14:20:20Z",
        created_by=CREATOR,
        closed_at="2026-07-28T18:02:11Z",
        resolution=Resolution.DONE,
        description="Publish a stable page for every bead.",
        notes="Verified with focused tests.",
        design="plan:202607/bead_pages.md",
    )
    phase_one = Issue(
        "sase-ai.1",
        "Pathing | links",
        status=Status.CLOSED,
        issue_type=IssueType.PHASE,
        parent_id=root.id,
        owner="owner@example.com",
        assignee="alice.athena.sase-ai.1",
        created_at="2026-07-28T14:30:00Z",
        created_by=CREATOR,
        closed_at="2026-07-28T15:00:00Z",
        resolution=Resolution.DONE,
        description="Define deterministic paths.",
        size=PhaseSize.SMALL,
        dependencies=[
            Dependency(
                issue_id="sase-ai.1",
                depends_on_id="sase-ai.2",
                created_at="2026-07-28T14:25:00Z",
            )
        ],
    )
    phase_two = Issue(
        "sase-ai.2",
        "Association index",
        status=Status.IN_PROGRESS,
        issue_type=IssueType.PHASE,
        parent_id=root.id,
        created_at="2026-07-28T14:45:00Z",
        size=PhaseSize.MEDIUM,
    )
    blocked = Issue(
        "sase-next",
        "Publication",
        issue_type=IssueType.PLAN,
        created_at="2026-07-27T17:00:00Z",
        dependencies=[
            Dependency(
                issue_id="sase-next",
                depends_on_id=phase_one.id,
                created_at="2026-07-28T15:10:00Z",
            )
        ],
    )
    agent = BeadAgentAssociation(
        "alice.athena.sase-ai.1",
        "https://github.com/sase-org/sase--agents/blob/main/agents/alice/README.md",
        phase_one.id,
        1,
        ("alice.athena.sase-ai.1", phase_one.id),
    )
    commit = BeadCommitAssociation(
        "9701511",
        "https://github.com/sase-org/sase/commit/9701511abcdef",
        phase_one.id,
        "feat(bead): render | pages",
        1_722_176_527,
        (1_722_176_527, "sase", "9701511abcdef"),
        "9701511abcdef",
        BeadCommitRepository("sase", Path("/repos/sase"), "primary", True),
    )
    phase_associations = BeadAssociations((agent,), (commit,))
    index = BeadAssociationIndex(
        MappingProxyType(
            {
                root.id: phase_associations,
                phase_one.id: phase_associations,
                phase_two.id: BeadAssociations(),
            }
        )
    )
    return View((root, phase_one, phase_two, blocked)), root, phase_one, index


def render_page(view: View, issue: Issue, index: BeadAssociationIndex) -> str:
    return render_bead_page(
        cast(BeadProject, view),
        issue,
        index,
        link_resolver=Links(),
    )
