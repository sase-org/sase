"""Rich rendering for ``sase skills list``."""

from __future__ import annotations

import argparse

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from sase.skills.inventory import (
    SkillSourceEntry,
    SkillTargetEntry,
    SkillTargetStatus,
    SkillsInventory,
    build_skills_inventory,
)

_STATUS_STYLES: dict[SkillTargetStatus, str] = {
    "current": "green",
    "stale": "yellow",
    "missing": "red",
}
_PROVIDER_STYLE = "cyan"
_DRIFT_LIMIT = 12


def handle_skills_list_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Render generated SASE skill source and target status."""
    _ = args
    inventory = build_skills_inventory()
    _render_skills_inventory(inventory, console=console)


def _render_skills_inventory(
    inventory: SkillsInventory,
    *,
    console: Console | None = None,
) -> None:
    """Print a Rich dashboard for ``inventory``."""
    target = console or Console()
    target.print(_build_skills_inventory_dashboard(inventory))


def _build_skills_inventory_dashboard(inventory: SkillsInventory) -> Group:
    """Build the static Rich dashboard for a skills inventory."""
    renderables: list[RenderableType] = [
        _summary_panel(inventory),
        _sources_table(inventory),
    ]
    drift = _drift_panel(inventory)
    if drift is not None:
        renderables.append(drift)
    renderables.append(_notes_panel())
    return Group(*renderables)


def _summary_panel(inventory: SkillsInventory) -> Panel:
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column()

    summary.add_row("Sources", str(inventory.source_count))
    summary.add_row("Providers", str(inventory.provider_count))
    summary.add_row("Generated targets", str(inventory.target_count))
    summary.add_row(
        "Target status",
        _status_counts(
            current=inventory.current_count,
            stale=inventory.stale_count,
            missing=inventory.missing_count,
        ),
    )
    summary.add_row("Deploy mode", inventory.deploy_mode)
    summary.add_row(
        "Output paths",
        "chezmoi source paths" if inventory.use_chezmoi else "home paths",
    )

    return Panel(summary, title="SASE Skills", border_style="cyan")


def _sources_table(inventory: SkillsInventory) -> Table | Panel:
    if not inventory.sources:
        return Panel(
            Text("No generated skill source entries found.", style="dim"),
            title="Skill Sources",
            border_style="cyan",
        )

    table = Table(
        title="Skill Sources",
        show_header=True,
        header_style="bold",
        box=None,
        expand=True,
        pad_edge=False,
    )
    table.add_column("Skill", no_wrap=True, overflow="ellipsis", width=18)
    table.add_column("Providers", no_wrap=True, overflow="ellipsis", width=11)
    table.add_column("Status", no_wrap=True, overflow="ellipsis", width=9)
    table.add_column("Source", no_wrap=True, overflow="ellipsis", width=18)
    table.add_column(
        "Description", no_wrap=True, overflow="ellipsis", min_width=16, ratio=1
    )

    for source in inventory.sources:
        table.add_row(
            Text(f"/{source.name}", style="bold cyan"),
            _provider_labels(source.providers),
            _source_status_summary(source),
            Text(_compact_path(source.source_path, limit=18), style="dim"),
            _description_cell(source.description),
        )
    return table


def _drift_panel(inventory: SkillsInventory) -> Panel | None:
    drift_targets = inventory.drift_targets
    if not drift_targets:
        return None

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Provider/Skill", no_wrap=True)
    table.add_column("Path")

    for target in drift_targets[:_DRIFT_LIMIT]:
        table.add_row(
            Text(target.status, style=_STATUS_STYLES[target.status]),
            Text(f"{target.provider}/{target.skill_name}"),
            Text(str(target.path)),
        )

    extra_count = len(drift_targets) - _DRIFT_LIMIT
    if extra_count > 0:
        table.add_row(
            Text("...", style="dim"),
            Text(f"+{extra_count} more", style="dim"),
            Text("run `sase skills init --force` to refresh", style="dim"),
        )

    return Panel(table, title="Drift", border_style="yellow")


def _notes_panel() -> Panel:
    notes = Text()
    notes.append("sase skills init --force refreshes generated skill files.\n")
    notes.append("sase init skills remains an alias-compatible initializer.")
    return Panel(notes, title="Notes", border_style="dim")


def _status_counts(*, current: int, stale: int, missing: int) -> Text:
    text = Text()
    _append_count(text, current, "current", "current")
    text.append(", ", style="dim")
    _append_count(text, stale, "stale", "stale")
    text.append(", ", style="dim")
    _append_count(text, missing, "missing", "missing")
    return text


def _source_status_summary(source: SkillSourceEntry) -> Text:
    text = Text()
    parts: list[tuple[int, SkillTargetStatus]] = [
        (source.current_count, "current"),
        (source.stale_count, "stale"),
        (source.missing_count, "missing"),
    ]
    visible_parts = [(count, status) for count, status in parts if count > 0]
    if not visible_parts:
        return Text("-", style="dim")

    for index, (count, status) in enumerate(visible_parts):
        if index:
            text.append(", ", style="dim")
        _append_count(text, count, status, status)
    return text


def _append_count(
    text: Text, count: int, label: str, status: SkillTargetStatus
) -> None:
    text.append(str(count), style=_STATUS_STYLES[status])
    text.append(f" {label}", style=_STATUS_STYLES[status])


def _provider_labels(providers: tuple[str, ...]) -> Text:
    if not providers:
        return Text("-", style="dim")

    labels = Text()
    first = providers[0]
    labels.append(first, style=f"bold {_PROVIDER_STYLE}")
    if len(providers) > 1:
        labels.append(f" +{len(providers) - 1}", style="dim")
    return labels


def _description_cell(description: str) -> Text | Syntax:
    if not description:
        return Text("-", style="dim")
    preview = _one_line(description)
    if any(marker in preview for marker in ("`", "*", "[")):
        return Syntax(
            preview,
            "markdown",
            theme="ansi_dark",
            background_color="default",
            word_wrap=False,
        )
    return Text(preview)


def _one_line(value: str, *, limit: int = 120) -> str:
    collapsed = " ".join(value.strip().split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _compact_path(value: str, *, limit: int = 120) -> str:
    collapsed = " ".join(value.strip().split())
    if len(collapsed) <= limit:
        return collapsed

    tail = collapsed.rsplit("/", maxsplit=1)[-1]
    compact = f".../{tail}"
    if len(compact) <= limit:
        return compact
    prefix = ".../"
    return prefix + _one_line(tail, limit=limit - len(prefix))
