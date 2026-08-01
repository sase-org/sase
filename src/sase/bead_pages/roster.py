"""Deterministic root-lineage roster for generated bead pages."""

from __future__ import annotations

from collections import Counter

from sase.agents_sync.rendering_markdown import md_cell, page_bytes
from sase.bead.model import Issue, IssueType
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.paths import bead_lineage_root
from sase.bead_type_presentation import bead_type_presentation


def _render_bead_pages_roster(
    issues: tuple[Issue, ...],
    association_index: BeadAssociationIndex,
) -> str:
    """Render the full root-bead roster without timestamps."""

    phase_counts = Counter(
        bead_lineage_root(issue.id)
        for issue in issues
        if issue.issue_type is IssueType.PHASE
    )
    roots = sorted(
        (issue for issue in issues if issue.id == bead_lineage_root(issue.id)),
        key=lambda issue: issue.id,
    )
    lines = [
        "# Bead Pages",
        "",
        "Generated pages for every bead lineage in this project.",
        "",
        "| Bead | Title | Type | Tier | Status | +1 | Phases | Agents | Commits |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for issue in roots:
        associations = association_index.for_bead(issue.id)
        tier = issue.tier.value if issue.tier is not None else "—"
        type_glyph = bead_type_presentation(issue.issue_type).glyph
        lines.append(
            "| "
            f"[{md_cell(issue.id)}]({issue.id}/README.md) | "
            f"{md_cell(issue.title)} | "
            f"{type_glyph} {issue.issue_type.value} | "
            f"{tier} | "
            f"{issue.status.value} | "
            f"{issue.plus_one_count} | "
            f"{phase_counts[issue.id]} | "
            f"{len(associations.agents)} | "
            f"{len(associations.commits)} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_bead_pages_roster_bytes(
    issues: tuple[Issue, ...],
    association_index: BeadAssociationIndex,
) -> bytes:
    """Return final publication bytes for the lineage roster."""

    return page_bytes(_render_bead_pages_roster(issues, association_index))


__all__ = ["render_bead_pages_roster_bytes"]
