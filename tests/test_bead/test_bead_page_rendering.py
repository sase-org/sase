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
from sase.bead_pages.roster import render_bead_pages_roster_bytes

_GOLDEN_DIR = Path(__file__).parent / "golden" / "bead_pages"
_CREATOR = "alice.athena.sase-ai.plan"
_CREATOR_URL = (
    "https://github.com/sase-org/sase--agents/blob/main/agents/"
    "alice.athena.sase-ai.plan/README.md"
)


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

    def agent_url(self, agent_name: str) -> str | None:
        assert agent_name == _CREATOR
        return _CREATOR_URL


class _ReferenceLinks:
    """A resolver with every hosted-link capability the page renderer uses."""

    def plan_url(self, plan_ref: str) -> str | None:
        return f"https://example.test/plans/{plan_ref.removeprefix('plans:')}"

    def bead_url(self, bead_id: str) -> str | None:
        return f"https://example.test/beads/{bead_id}.md"

    def agent_url(self, agent_name: str) -> str | None:
        return None

    def commit_url(self, sha: str) -> str | None:
        return f"https://example.test/commit/{sha}"


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
        created_by=_CREATOR,
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
        created_by=_CREATOR,
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


def test_pages_omit_the_reference_section_when_a_bead_stores_none() -> None:
    view, root, _phase, index = _fixtures()

    assert "## References" not in _render(view, root, index)


def test_created_by_renders_as_a_link_when_the_resolver_has_one() -> None:
    view, root, _phase, index = _fixtures()

    rendered = _render(view, root, index)

    assert f"**Created by:** [{_CREATOR}]({_CREATOR_URL})" in rendered


def test_created_by_renders_as_code_when_the_resolver_has_no_link() -> None:
    view, root, _phase, index = _fixtures()

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=_ReferenceLinks(),
    )

    assert f"**Created by:** `{_CREATOR}`" in rendered
    assert f"[{_CREATOR}]" not in rendered


def test_empty_created_by_leaves_the_ownership_line_unchanged() -> None:
    view, root, _phase, index = _fixtures()
    root.created_by = ""

    rendered = _render(view, root, index)

    assert (
        "**Owner:** `owner@example.com` · **Assignee:** `alice.athena.sase-ai.land`"
        in rendered
    )
    assert "**Created by:**" not in rendered


def test_references_link_only_where_the_resolver_produces_a_url() -> None:
    view, root, _phase, index = _fixtures()
    root.refs = [
        "plans:202607/bead_pages.md",
        "bead:sase-ai",
        "commit:sase@9701511abcdef",
        "agent:alice.athena.sase-ai.1",
        "research:202607/capture.md",
    ]

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=_ReferenceLinks(),
    )

    assert "## References" in rendered
    assert (
        "- [plans:202607/bead\\_pages.md]"
        "(https://example.test/plans/202607/bead_pages.md)" in rendered
    )
    assert "- [bead:sase-ai](https://example.test/beads/sase-ai.md)" in rendered
    assert (
        "- [commit:sase@9701511abcdef](https://example.test/commit/9701511abcdef)"
        in rendered
    )
    # The resolver declines these, so they must stay plain text, never a link.
    assert "- agent:alice.athena.sase-ai.1" in rendered
    assert "- research:202607/capture.md" in rendered


def test_an_unparseable_reference_renders_as_escaped_plain_text() -> None:
    view, root, _phase, index = _fixtures()
    root.refs = ["not a reference [x](https://evil.test)"]

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        index,
        link_resolver=_ReferenceLinks(),
    )

    # The escaped brackets keep Markdown from forming a link out of the value.
    assert "- not a reference \\[x\\](https://evil.test)" in rendered
    assert "- [not a reference" not in rendered


def test_references_render_without_any_link_resolver() -> None:
    view, root, _phase, index = _fixtures()
    root.refs = ["plans:202607/bead_pages.md"]

    rendered = render_bead_page(cast(BeadProject, view), root, index)

    assert "- plans:202607/bead\\_pages.md" in rendered


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


def test_task_bead_page_renders_the_task_identity_and_ready_status() -> None:
    task = Issue(
        "sase-task",
        "Fix the flaky linter",
        status=Status.READY,
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        description="Discovered while landing sase-ai.",
    )
    view = _View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "**Status:** ◇ ready · **Type:** ◆ task" in rendered
    assert "**Size:** small" in rendered
    assert "[Bead Pages](../README.md) / sase-task" in rendered


def test_roster_renders_every_bead_type_with_its_shared_glyph() -> None:
    epic = Issue(
        "sase-ai",
        "Published bead pages",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
    )
    phase = Issue(
        "sase-ai.1",
        "Pathing",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
    )
    task = Issue(
        "sase-task",
        "Fix the flaky linter",
        status=Status.READY,
        issue_type=IssueType.TASK,
    )

    rendered = render_bead_pages_roster_bytes(
        (epic, phase, task),
        BeadAssociationIndex(MappingProxyType({})),
    ).decode()

    # Phases are rolled into their lineage root, so only roots get a row.
    assert (
        "| [sase-ai](sase-ai/README.md) | Published bead pages | ▸ plan |" in rendered
    )
    assert "| [sase-task](sase-task/README.md) | Fix the flaky linter | ◆ task |" in (
        rendered
    )
    assert "sase-ai.1" not in rendered
