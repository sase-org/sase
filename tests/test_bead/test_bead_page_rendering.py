"""Golden and structural coverage for generated bead pages."""

from __future__ import annotations

from types import MappingProxyType
from typing import cast

from sase.bead.model import Issue, IssueType
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.rendering import render_bead_page, render_bead_page_bytes
from sase.bead_pages.rendering_graph import MAX_RENDERED_LINEAGE_NODES
from tests.test_bead.bead_page_rendering_test_helpers import (
    GOLDEN_DIR,
    Links,
    View,
    fixtures,
    render_page,
)


def test_root_and_descendant_pages_match_goldens_and_are_byte_stable() -> None:
    view, root, phase, index = fixtures()

    root_page = render_page(view, root, index)
    phase_page = render_page(view, phase, index)

    assert root_page == (GOLDEN_DIR / "root.txt").read_text(encoding="utf-8")
    assert phase_page == (GOLDEN_DIR / "descendant.txt").read_text(encoding="utf-8")
    assert (
        render_bead_page_bytes(
            cast(BeadProject, view),
            root,
            index,
            link_resolver=Links(),
        )
        == root_page.encode()
    )
    assert render_page(view, root, index) == root_page


def test_relationship_rows_carry_the_absolute_creation_date() -> None:
    view, root, phase, index = fixtures()

    root_page = render_page(view, root, index)
    phase_page = render_page(view, phase, index)

    assert "| Bead | Title | Status | Size | Created | Agents | Commits |" in root_page
    assert "| ✓ closed | small | 2026-07-28 |" in root_page
    assert "- **Depends on:** [sase-ai.2](sase-ai.2.md) ◐ · ⧖ 2026-07-28" in phase_page
    # Persisted pages never carry a relative age; their bytes must not drift.
    assert " ago" not in root_page
    assert " ago" not in phase_page


def test_relationship_rows_stay_honest_when_a_bead_has_no_creation_time() -> None:
    view, root, phase, index = fixtures()
    for issue in view.list_issues():
        issue.created_at = ""

    root_page = render_page(view, root, index)
    phase_page = render_page(view, phase, index)

    assert "| ✓ closed | small | unknown |" in root_page
    assert "- **Depends on:** [sase-ai.2](sase-ai.2.md) ◐\n" in phase_page


def test_structural_markdown_in_authored_text_is_neutralized() -> None:
    view, _root, phase, index = fixtures()
    phase.title = "Unsafe | `title` # still one heading"
    phase.description = "intro\n# injected\n```python\nunsafe\n```\nnormal | Markdown"

    rendered = render_page(view, phase, index)

    assert rendered.count("\n# ") == 0
    assert rendered.count("## Description") == 1
    assert "\n\\# injected\n" in rendered
    assert "\n\\```python\n" in rendered
    assert "\n\\```\n" in rendered
    assert "# Bead: sase-ai.1 — Unsafe \\| \\`title\\` # still one heading" in rendered


def test_empty_optional_sections_are_omitted() -> None:
    root = Issue("sase-empty", "Empty", issue_type=IssueType.PLAN)
    view = View((root,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        BeadAssociationIndex(MappingProxyType({})),
    )

    for heading in (
        "## Previously Closed",
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
    view = View((root, *phases))

    rendered = render_bead_page(
        cast(BeadProject, view),
        root,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "## Lineage" not in rendered
    assert "… and 0 more phases" not in rendered
