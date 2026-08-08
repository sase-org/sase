"""Rich rendering for ``sase skill list``."""

from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.skills.inventory import (
    SkillSourceEntry,
    SkillTargetEntry,
    SkillTargetStatus,
    SkillsInventory,
    build_skills_inventory,
)

__all__ = [
    "SkillTargetEntry",
    "handle_skills_list_command",
]

_STATUS_STYLES: dict[SkillTargetStatus, str] = {
    "current": "green",
    "stale": "yellow",
    "missing": "red",
}
_STATUS_ICONS: dict[SkillTargetStatus, str] = {
    "current": "✓",
    "stale": "⚠",
    "missing": "✗",
}
_PROVIDER_COLORS: dict[str, str] = {
    "claude": "#cc785c",
    "agy": "#6e5de7",
    "codex": "#10a37f",
    "amp": "magenta",
    "cursor": "cyan",
}
_PROVIDER_ORDER: tuple[str, ...] = ("claude", "agy", "codex", "amp", "cursor")
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
    misplaced = _placement_panel(inventory)
    if misplaced is not None:
        renderables.append(misplaced)
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
        expand=True,
        show_lines=True,
        header_style="bold",
    )
    table.add_column("Skill", no_wrap=False, overflow="fold", min_width=16)
    table.add_column("Providers", no_wrap=False, overflow="fold", ratio=2, min_width=14)
    table.add_column("Status", no_wrap=False, overflow="fold", min_width=7)
    table.add_column(
        "Description", no_wrap=False, overflow="fold", ratio=3, min_width=20
    )

    for source in inventory.sources:
        table.add_row(
            Text(f"/{source.name}", style="bold cyan"),
            _provider_chips(source.providers),
            _status_tokens(source),
            _details_cell(source),
        )
    return table


def _details_cell(source: SkillSourceEntry) -> RenderableType:
    description = _normalize_whitespace(source.description) or "-"
    description_text = Text(description)
    footer = _compact_source_path(source.source_path, source.name)
    if footer is None:
        return description_text
    return Group(description_text, footer)


def _placement_panel(inventory: SkillsInventory) -> Panel | None:
    """Report sources the canonical placement rules excluded, if any.

    ``sase skill list`` is read-only, so it warns here while ``sase skill
    init`` refuses outright.
    """
    if not inventory.placement_errors:
        return None

    body = Text()
    for index, message in enumerate(inventory.placement_errors):
        if index:
            body.append("\n")
        body.append(message, style="yellow")
    return Panel(body, title="Misplaced Sources", border_style="yellow")


def _drift_panel(inventory: SkillsInventory) -> Panel | None:
    drift_targets = inventory.drift_targets
    if not drift_targets:
        return None

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Status", no_wrap=True)
    table.add_column("Provider/Skill", no_wrap=True)
    table.add_column("Path", no_wrap=False, overflow="fold")

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
            Text("run `sase skill init --force` to refresh", style="dim"),
        )

    return Panel(table, title="Drift", border_style="yellow")


def _notes_panel() -> Panel:
    notes = Text()
    notes.append("sase skill init --force refreshes generated skill files.\n")
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


def _status_tokens(source: SkillSourceEntry) -> Text:
    parts: list[tuple[int, SkillTargetStatus]] = [
        (source.current_count, "current"),
        (source.stale_count, "stale"),
        (source.missing_count, "missing"),
    ]
    visible: list[tuple[int, SkillTargetStatus]] = [
        (count, status) for count, status in parts if count > 0
    ]
    if not visible:
        return Text("–", style="dim")

    text = Text()
    for index, (count, status) in enumerate(visible):
        if index:
            text.append(" ")
        style = _STATUS_STYLES[status]
        text.append(f"{_STATUS_ICONS[status]} {count}", style=style)
    return text


def _append_count(
    text: Text, count: int, label: str, status: SkillTargetStatus
) -> None:
    text.append(str(count), style=_STATUS_STYLES[status])
    text.append(f" {label}", style=_STATUS_STYLES[status])


def _provider_chips(providers: tuple[str, ...]) -> Text:
    if not providers:
        return Text("–", style="dim")

    seen = set(providers)
    known = [p for p in _PROVIDER_ORDER if p in seen]
    unknown = sorted(p for p in providers if p not in _PROVIDER_COLORS)
    ordered = known + unknown

    text = Text()
    for index, provider in enumerate(ordered):
        if index:
            text.append("  ")
        color = _PROVIDER_COLORS.get(provider, "white")
        text.append("●", style=color)
        text.append(f" {provider}", style=color)
    return text


def _compact_source_path(source_path: str, skill_name: str) -> Text | None:
    if not source_path or source_path == "-":
        return None

    if _is_special_prefix_path(source_path):
        return Text(source_path, style="dim")

    # Bundled skills are the uninteresting default, so only user, project, and
    # plugin sources are worth a path footer.
    if _is_packaged_source(source_path, skill_name):
        return None

    compact = source_path
    home = str(Path.home())
    if home and compact.startswith(home):
        compact = "~" + compact[len(home) :]

    marker = "/skills/"
    if marker in compact:
        basename = compact.rsplit("/", 1)[-1]
        compact = f"…/skills/{basename}"

    return Text(compact, style="dim")


def _is_packaged_source(source_path: str, skill_name: str) -> bool:
    from sase.xprompt.loader_skills import get_sase_package_skills_dir

    packaged = get_sase_package_skills_dir() / f"{skill_name}.md"
    return source_path == str(packaged)


def _is_special_prefix_path(source_path: str) -> bool:
    if source_path.startswith(("/", "~", ".")):
        return False
    head, _, _ = source_path.partition(":")
    return bool(head) and head.isidentifier()


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.strip().split())
