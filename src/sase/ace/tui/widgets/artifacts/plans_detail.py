"""Rich properties and Markdown bodies for document rows in Plans."""

from __future__ import annotations

from pathlib import Path

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from sase.artifact_refs import parse_artifact_ref
from sase.bead_status_presentation import bead_status_presentation
from sase.plan_search.model import PlanSearchMatch
from sase.sdd.plan_properties import ordered_plan_property_items, plan_property_label
from sase.sdd.plan_refs import PLAN_REFERENCE_KIND

from .bead_plan_links import BeadPlanLink
from .plans_data import ActivePlanDocument, PlanProposal

DetailProperty = tuple[str, str | Text]


def proposal_properties_header(
    proposal: PlanProposal,
    *,
    project_name: str,
) -> RenderableType:
    """Build a proposal title and complete property grid."""
    title = Text("◆ ", style="bold #FFD700")
    title.append(proposal.title, style="bold white")
    proposed = proposal.timestamp or "—"
    if proposal.age:
        proposed += f"  ·  {proposal.age}"
    properties: list[DetailProperty] = [
        ("State", _chip("pending approval", "#FFD700", glyph="◆")),
        ("Tier", proposal.tier),
        ("Agent", proposal.agent),
        ("Model", proposal.provider_model),
        ("Proposed", proposed),
        ("Project", project_name),
        ("Path", proposal.plan_path),
    ]
    properties.extend(_frontmatter_properties(proposal.frontmatter))
    return _properties_header(title, properties)


def active_plan_properties_header(
    active: ActivePlanDocument,
    *,
    project_name: str,
) -> RenderableType:
    """Build properties for one plan linked from a live bead."""
    document = active.document
    title = Text("▤ ", style="bold #AF87FF")
    title.append(
        _document_title(document.path, document.frontmatter), style="bold white"
    )
    properties = list(_frontmatter_properties(document.frontmatter))
    properties.extend(
        [
            ("Owning bead", active.owner.bead_id),
            ("Bead status", _status_chip(active.owner)),
            ("Design reference", active.owner.reference),
            ("Project", project_name),
            ("Path", document.path),
        ]
    )
    return _properties_header(title, properties)


def archive_properties_header(
    match: PlanSearchMatch,
    *,
    project_name: str,
    role: str = PLAN_REFERENCE_KIND,
    owner: BeadPlanLink | None = None,
) -> RenderableType:
    """Build an archived-plan title and complete property grid."""
    plan = match.plan
    title = Text("▤ ", style="bold #00D7AF")
    title.append(plan.title or plan.name, style="bold white")
    properties = list(_frontmatter_properties(plan.frontmatter))
    if owner is not None:
        properties.extend(
            [
                ("Owning bead", owner.bead_id),
                ("Bead status", _status_chip(owner)),
                ("Design reference", owner.reference),
            ]
        )
    properties.extend(
        [
            ("Source", plan.source),
            ("Project", project_name),
            ("Reference", _archive_reference(match, role=role)),
            ("Path", plan.path),
        ]
    )
    return _properties_header(title, properties)


def archive_preview_markdown(
    match: PlanSearchMatch, *, role: str = PLAN_REFERENCE_KIND
) -> str:
    """Build the full-screen archive preview content."""
    plan = match.plan
    lines = [
        f"# {plan.title or plan.name}",
        "",
        f"**Tier:** {plan.kind}  ",
        f"**Status:** {plan.status or 'unknown'}  ",
        f"**Created:** {plan.created_at or '—'}  ",
        f"**Reference:** {_archive_reference(match, role=role)}  ",
        f"**Path:** {plan.path}",
        "",
    ]
    if plan.summary:
        lines.extend(["> " + plan.summary.replace("\n", "\n> "), ""])
    lines.append(plan.body or "_No plan body._")
    return "\n".join(lines)


def _document_title(path: str, frontmatter: dict[str, str]) -> str:
    return (
        frontmatter.get("title")
        or Path(path).stem.replace("_", " ").replace("-", " ").title()
    )


def _archive_reference(match: PlanSearchMatch, *, role: str) -> str:
    return parse_artifact_ref(f"{role}:{match.plan.relpath}").rendered


def _properties_header(
    title: Text,
    properties: list[DetailProperty],
) -> RenderableType:
    table = Table.grid(padding=(0, 1), expand=True)
    table.add_column(justify="right", style="dim", no_wrap=True)
    table.add_column(ratio=1, overflow="fold")
    for label, value in properties:
        table.add_row(label, _property_text(value))
    divider = Text("─" * 72, style="dim #5F5F87", no_wrap=True, overflow="crop")
    return Group(title, table, divider)


def _property_text(value: str | Text) -> Text:
    if isinstance(value, Text):
        return value
    if value:
        return Text(value, style="white", overflow="fold")
    return Text("—", style="dim")


def _frontmatter_properties(
    frontmatter: dict[str, str],
) -> tuple[DetailProperty, ...]:
    return tuple(
        (plan_property_label(key), value)
        for key, value in ordered_plan_property_items(frontmatter)
    )


def _chip(label: str, color: str, *, glyph: str = "") -> Text:
    prefix = f"{glyph} " if glyph else ""
    text = Text()
    text.append(f" {prefix}{label} ", style=f"bold #1a1a1a on {color}")
    text.append(" ")
    return text


def _status_chip(owner: BeadPlanLink) -> Text:
    presentation = bead_status_presentation(owner.bead_status)
    return _chip(
        owner.bead_status.value.replace("_", " "),
        presentation.rich_color,
        glyph=presentation.tui_glyph,
    )


__all__ = [
    "active_plan_properties_header",
    "archive_preview_markdown",
    "archive_properties_header",
    "proposal_properties_header",
]
