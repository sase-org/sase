"""Rich rendering for the plan inventory."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.main.plan_inventory_models import (
    DEFAULT_HISTORY_LIMIT,
    ApprovedPlan,
    PlanInventory,
    ProposedPlan,
    RejectedPlan,
    selected_statuses,
    tier_counts,
)

_ApprovedCandidateLimit = Callable[[int], int | None]
_AgentProject = Callable[[str, str], str]


def render_plan_inventory(
    inventory: PlanInventory,
    *,
    console: Any | None,
    approved_candidate_limit: _ApprovedCandidateLimit,
    agent_project: _AgentProject,
) -> None:
    """Render the inventory as a compact Rich dashboard."""
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    rich_console = console or Console()
    selected = selected_statuses(inventory)

    summary = Table.grid(expand=True)
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_column(justify="center")
    summary.add_row(
        _summary_cell(
            "Proposed",
            len(inventory.proposed),
            "yellow",
            dimmed="proposed" not in selected,
        ),
        _summary_cell(
            "Approved shown",
            len(inventory.approved),
            "green",
            dimmed="approved" not in selected,
        ),
        _summary_cell(
            "Rejected shown",
            len(inventory.rejected),
            "red",
            dimmed="rejected" not in selected,
        ),
        _summary_cell("Archived total", inventory.total_archived_proposals, "cyan"),
    )
    rich_console.print(
        Panel(summary, title="Plan Pipeline", border_style="cyan", box=box.ROUNDED)
    )
    filters = _filters_line(inventory)
    if filters is not None:
        rich_console.print(filters)

    if "proposed" in selected:
        rich_console.print(
            _section_panel(
                f"Proposed ({len(inventory.proposed)})",
                _proposed_table(inventory.proposed, agent_project=agent_project),
                empty="No pending plan proposals.",
                border_style="yellow",
            )
        )
    if "approved" in selected:
        truncation_note = None
        if inventory.approved_scan_truncated:
            candidate_limit = approved_candidate_limit(inventory.limit)
            truncation_note = (
                f"Scanned the newest {candidate_limit} agent artifacts; "
                "older approvals may exist."
            )
        rich_console.print(
            _section_panel(
                f"Approved ({len(inventory.approved)})",
                _approved_table(inventory.approved, agent_project=agent_project),
                empty="No approved plans found.",
                border_style="green",
                note=truncation_note,
            )
        )
    if "rejected" in selected:
        rich_console.print(
            _section_panel(
                f"Rejected ({len(inventory.rejected)})",
                _rejected_table(inventory.rejected),
                empty="No inferred rejected plans.",
                border_style="red",
            )
        )


def _summary_cell(label: str, value: int, style: str, *, dimmed: bool = False) -> Any:
    from rich.text import Text

    text = Text()
    text.append(str(value), style=f"bold {style}")
    text.append(f"\n{label}", style="dim")
    if dimmed:
        text.stylize("dim")
    return text


def _section_panel(
    title: str,
    table: Any | None,
    *,
    empty: str,
    border_style: str,
    note: str | None = None,
) -> Any:
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    content = table if table is not None else Text(empty, style="dim")
    if note:
        content = Group(content, Text(note, style="dim"))
    return Panel(content, title=title, border_style=border_style, box=box.ROUNDED)


def _filters_line(inventory: PlanInventory) -> Any | None:
    if (
        not inventory.status_filter
        and not inventory.tier_filter
        and inventory.limit == DEFAULT_HISTORY_LIMIT
    ):
        return None

    from rich.text import Text

    line = Text("Filters: ", style="dim")
    separator_needed = False
    if inventory.status_filter:
        line.append("status=", style="dim")
        line.append(",".join(inventory.status_filter))
        separator_needed = True
    if inventory.tier_filter:
        if separator_needed:
            line.append(" · ", style="dim")
        counts = tier_counts(inventory)
        line.append("tier=", style="dim")
        for index, tier in enumerate(inventory.tier_filter):
            if index:
                line.append(",")
            line.append(tier, style=_tier_style(tier))
            line.append(f": {counts[tier]}")
        separator_needed = True
    if inventory.limit != DEFAULT_HISTORY_LIMIT:
        if separator_needed:
            line.append(" · ", style="dim")
        line.append("limit=", style="dim")
        line.append(str(inventory.limit))
    return line


def _proposed_table(
    rows: tuple[ProposedPlan, ...], *, agent_project: _AgentProject
) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("ID", no_wrap=True, style="yellow")
    table.add_column("Age", no_wrap=True)
    table.add_column("Agent/Project")
    table.add_column("Model")
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    for row in rows:
        table.add_row(
            row.id_prefix,
            row.age,
            agent_project(row.agent, row.project),
            row.provider_model,
            _tier_text(row.tier),
            row.plan_path,
        )
    return table


def _approved_table(
    rows: tuple[ApprovedPlan, ...], *, agent_project: _AgentProject
) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("Approved", no_wrap=True)
    table.add_column("Action", no_wrap=True, style="green")
    table.add_column("Agent/Project")
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    for row in rows:
        table.add_row(
            row.age,
            row.action,
            agent_project(row.agent, row.project),
            _tier_text(row.tier),
            row.plan_path,
        )
    return table


def _rejected_table(rows: tuple[RejectedPlan, ...]) -> Any | None:
    if not rows:
        return None
    table = _base_table()
    table.add_column("Archived", no_wrap=True)
    table.add_column("Tier", no_wrap=True)
    table.add_column("Plan path", ratio=2, overflow="fold")
    table.add_column("Note", ratio=1)
    for row in rows:
        table.add_row(row.age, _tier_text(row.tier), row.plan_path, row.note)
    return table


def _base_table() -> Any:
    from rich import box
    from rich.table import Table

    return Table(box=box.SIMPLE, expand=True, show_edge=False)


def _tier_style(tier: str) -> str:
    return "green" if tier == "tale" else "magenta" if tier == "epic" else "dim"


def _tier_text(tier: str) -> Any:
    from rich.text import Text

    return Text(tier, style=_tier_style(tier))
