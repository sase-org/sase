"""Golden and adversarial coverage for generated bead pages."""

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
from sase.bead_pages.rendering import render_bead_page, render_bead_page_bytes
from sase.bead_pages.rendering_graph import MAX_RENDERED_LINEAGE_NODES

_GOLDEN_DIR = Path(__file__).parent / "golden" / "bead_pages"


class _View:
    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self._issues = {issue.id: issue for issue in issues}

    def show(self, issue_id: str) -> Issue:
        return self._issues[issue_id]

    def list_issues(self) -> list[Issue]:
        return list(self._issues.values())

    def get_epic_children(self, issue_id: str) -> list[Issue]:
        return [issue for issue in self._issues.values() if issue.parent_id == issue_id]


class _Links:
    def plan_url(self, plan_ref: str) -> str | None:
        assert plan_ref == "plans:202607/bead_pages.md"
        return "https://github.com/sase-org/sase--plans/blob/main/202607/bead_pages.md"


def _fixtures() -> tuple[_View, Issue, Issue, BeadAssociationIndex]:
    root = Issue(
        "sase-ai",
        "Published bead pages",
        status=Status.CLOSED,
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        owner="owner@example.com",
        assignee="alice.athena.sase-ai.land",
        created_at="2026-07-28T14:20:20Z",
        closed_at="2026-07-28T18:02:11Z",
        resolution=Resolution.DONE,
        description="Publish a stable page for every bead.",
        notes="Verified with focused tests.",
        design="plans:202607/bead_pages.md",
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
        size=PhaseSize.MEDIUM,
    )
    blocked = Issue(
        "sase-next",
        "Publication",
        issue_type=IssueType.PLAN,
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
    return _View((root, phase_one, phase_two, blocked)), root, phase_one, index


def _render(view: _View, issue: Issue, index: BeadAssociationIndex) -> str:
    return render_bead_page(
        cast(BeadProject, view),
        issue,
        index,
        link_resolver=_Links(),
    )


def test_root_and_descendant_pages_match_goldens_and_are_byte_stable() -> None:
    view, root, phase, index = _fixtures()

    root_page = _render(view, root, index)
    phase_page = _render(view, phase, index)

    assert root_page == (_GOLDEN_DIR / "root.txt").read_text(encoding="utf-8")
    assert phase_page == (_GOLDEN_DIR / "descendant.txt").read_text(encoding="utf-8")
    assert (
        render_bead_page_bytes(
            cast(BeadProject, view),
            root,
            index,
            link_resolver=_Links(),
        )
        == root_page.encode()
    )
    assert _render(view, root, index) == root_page


def test_structural_markdown_in_authored_text_is_neutralized() -> None:
    view, _root, phase, index = _fixtures()
    phase.title = "Unsafe | `title` # still one heading"
    phase.description = "intro\n# injected\n```python\nunsafe\n```\nnormal | Markdown"

    rendered = _render(view, phase, index)

    assert rendered.count("\n# ") == 0
    assert rendered.count("## Description") == 1
    assert "\n\\# injected\n" in rendered
    assert "\n\\```python\n" in rendered
    assert "\n\\```\n" in rendered
    assert "# Bead: sase-ai.1 — Unsafe \\| \\`title\\` # still one heading" in rendered


def test_lists_are_visibly_bounded_at_the_shared_commit_cap() -> None:
    view, _root, phase, _index = _fixtures()
    commits = tuple(
        BeadCommitAssociation(
            f"{number:07d}",
            None,
            phase.id,
            f"subject {number}",
            number,
            (number, "sase", f"{number:040d}"),
            f"{number:040d}",
        )
        for number in range(52)
    )
    index = BeadAssociationIndex(
        MappingProxyType({phase.id: BeadAssociations(commits=commits)})
    )

    rendered = _render(view, phase, index)

    assert "… and 2 more commits" in rendered
    assert "subject 49" in rendered
    assert "subject 50" not in rendered


def test_unhosted_page_keeps_labels_and_omits_broken_urls() -> None:
    view, _root, phase, index = _fixtures()
    hosted = index.for_bead(phase.id)
    unhosted = BeadAssociations(
        agents=tuple(
            BeadAgentAssociation(
                row.label,
                None,
                row.bead_id,
                row.commit_count,
                row.sort_key,
            )
            for row in hosted.agents
        ),
        commits=tuple(
            BeadCommitAssociation(
                row.label,
                None,
                row.bead_id,
                row.subject,
                row.committed_at,
                row.sort_key,
                row.sha,
                row.repository,
            )
            for row in hosted.commits
        ),
    )

    rendered = render_bead_page(
        cast(BeadProject, view),
        phase,
        BeadAssociationIndex(MappingProxyType({phase.id: unhosted})),
    )

    assert "alice.athena.sase-ai.1" in rendered
    assert "`9701511`" in rendered
    assert "202607/bead\\_pages.md" in rendered
    assert "https://" not in rendered


def test_commit_repo_is_rendered_in_its_own_column(
    tmp_path: Path,
) -> None:
    view, _root, phase, index = _fixtures()
    original = index.for_bead(phase.id).commits[0]
    primary = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
        BeadCommitRepository("sase", tmp_path / "sase", "primary", True),
    )
    linked = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
        BeadCommitRepository(
            "sase-core",
            tmp_path / "sase-core",
            "linked",
            False,
        ),
    )

    original_page = _render(view, phase, index)
    original_associations = index.for_bead(phase.id)
    primary_page = _render(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType(
                {
                    phase.id: BeadAssociations(
                        agents=original_associations.agents,
                        commits=(primary,),
                    )
                }
            )
        ),
    )
    linked_page = _render(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType(
                {
                    phase.id: BeadAssociations(
                        agents=original_associations.agents,
                        commits=(linked,),
                    )
                }
            )
        ),
    )

    assert primary_page == original_page
    assert "| sase | [`9701511`]" in primary_page
    assert "| sase-core | [`9701511`]" in linked_page
    assert "@9701511" not in primary_page
    assert "@9701511" not in linked_page
    assert primary_page.replace("| sase |", "| sase-core |") == linked_page


def test_commit_repo_column_has_unknown_fallback() -> None:
    view, _root, phase, index = _fixtures()
    original = index.for_bead(phase.id).commits[0]
    unknown = BeadCommitAssociation(
        original.label,
        original.target,
        original.bead_id,
        original.subject,
        original.committed_at,
        original.sort_key,
        original.sha,
    )

    rendered = _render(
        view,
        phase,
        BeadAssociationIndex(
            MappingProxyType({phase.id: BeadAssociations(commits=(unknown,))})
        ),
    )

    assert "| Repo | Commit | Subject | Bead | Committed (UTC) |" in rendered
    assert "| — | [`9701511`]" in rendered


def test_empty_optional_sections_are_omitted() -> None:
    root = Issue("sase-empty", "Empty", issue_type=IssueType.PLAN)
    view = _View((root,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        BeadAssociationIndex(MappingProxyType({})),
    )

    for heading in (
        "## Description",
        "## Notes",
        "## Phases",
        "## Dependencies",
        "## Agents",
        "## Commits",
    ):
        assert heading not in rendered


def test_lineage_graph_is_omitted_above_its_node_cap() -> None:
    root = Issue("sase-wide", "Wide", issue_type=IssueType.PLAN)
    phases = tuple(
        Issue(
            f"{root.id}.{number}",
            f"Phase {number}",
            issue_type=IssueType.PHASE,
            parent_id=root.id,
        )
        for number in range(MAX_RENDERED_LINEAGE_NODES)
    )
    view = _View((root, *phases))

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "## Lineage" not in rendered
    assert "… and 0 more phases" not in rendered
