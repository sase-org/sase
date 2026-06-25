"""Rich rendering for the ``sase plugin`` commands.

Phase 2 renders the ``sase plugin list`` catalog: a single titled panel holding a
built-in section, a community section (led by an unmissable warning), and a footer
with a glyph legend, counts, and the cache-age + refresh affordance. Color enhances
but is never load-bearing — glyphs and explicit labels carry the meaning so the
output stays legible when copied into an agent chat or a no-color terminal.
"""

from __future__ import annotations

import time

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry

#: Glyphs (never color alone) for installed vs. available plugins.
_INSTALLED_GLYPH = "●"
_AVAILABLE_GLYPH = "○"

#: Placeholder for an empty cell (em dash).
_EMPTY = "—"

_BUILTIN_STYLE = "green"
_COMMUNITY_STYLE = "yellow"

#: The community section header *is* the warning, so the built-in/community
#: distinction is impossible to miss.
_COMMUNITY_WARNING = (
    "⚠ third-party, not maintained by sase-org — review before installing"
)

_REFRESH_COMMAND = "`sase plugin list --refresh`"


def render_catalog_list(
    catalog: PluginCatalog,
    *,
    verbose: bool = False,
    now: float | None = None,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin list`` catalog panel to *console*."""
    target = console or Console()
    target.print(_build_list_panel(catalog, verbose=verbose, now=now))


def _build_list_panel(
    catalog: PluginCatalog, *, verbose: bool, now: float | None
) -> Panel:
    now = time.time() if now is None else now
    body: list[RenderableType] = []

    for warning in catalog.warnings:
        body.append(Text(f"⚠ {warning}", style="yellow"))
    if catalog.warnings:
        body.append(Text(""))

    if not catalog.entries:
        body.append(Text("No SASE plugins found.", style="dim"))
    else:
        if catalog.builtin_entries:
            body.append(
                _section_header("BUILT-IN", "sase-org (official)", _BUILTIN_STYLE)
            )
            body.append(_entries_table(catalog.builtin_entries, verbose=verbose))
        if catalog.community_entries:
            if catalog.builtin_entries:
                body.append(Text(""))
            body.append(
                _section_header("COMMUNITY", _COMMUNITY_WARNING, _COMMUNITY_STYLE)
            )
            body.append(_entries_table(catalog.community_entries, verbose=verbose))

    body.append(Text(""))
    body.append(_legend_counts(catalog))
    body.append(_cache_line(catalog, now=now))

    return Panel(Group(*body), title="SASE Plugins", border_style="cyan")


def _section_header(label: str, suffix: str, style: str) -> Text:
    header = Text()
    header.append(label, style=f"bold {style}")
    header.append("  ·  ", style="dim")
    header.append(suffix, style=style)
    return header


def _entries_table(entries: tuple[PluginCatalogEntry, ...], *, verbose: bool) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)  # installed glyph
    table.add_column(style="bold", no_wrap=True)  # short name
    table.add_column(no_wrap=True)  # installed version
    table.add_column(no_wrap=True)  # entry-point groups
    if verbose:
        table.add_column(no_wrap=True, justify="right")  # stars
        table.add_column(no_wrap=True)  # last updated
    table.add_column()  # description (+ topics when verbose)

    for entry in entries:
        row: list[RenderableType] = [
            _glyph(entry),
            Text(entry.name),
            _version_cell(entry),
            _groups_cell(entry),
        ]
        if verbose:
            row.append(Text(f"★ {entry.stars}", style="dim"))
            row.append(Text(entry.updated_at or _EMPTY, style="dim"))
        row.append(_description_cell(entry, verbose=verbose))
        table.add_row(*row)

    return table


def _glyph(entry: PluginCatalogEntry) -> Text:
    if entry.installed.installed:
        return Text(_INSTALLED_GLYPH, style="green")
    return Text(_AVAILABLE_GLYPH, style="dim")


def _version_cell(entry: PluginCatalogEntry) -> Text:
    info = entry.installed
    if not info.installed:
        return Text(_EMPTY, style="dim")
    if info.version:
        return Text(f"v{info.version}", style="green")
    return Text("installed", style="green")


def _groups_cell(entry: PluginCatalogEntry) -> Text:
    groups = entry.installed.entry_point_groups
    if not groups:
        return Text(_EMPTY, style="dim")
    return Text(", ".join(groups), style="dim")


def _description_cell(entry: PluginCatalogEntry, *, verbose: bool) -> Text:
    description = Text(entry.description or _EMPTY)
    if entry.archived:
        description.append("  (archived)", style="red")
    if verbose and entry.topics:
        description.append("\n")
        description.append("topics: " + " · ".join(entry.topics), style="dim")
    return description


def _legend_counts(catalog: PluginCatalog) -> Text:
    line = Text()
    line.append(_INSTALLED_GLYPH, style="green")
    line.append(" installed   ", style="dim")
    line.append(_AVAILABLE_GLYPH, style="dim")
    line.append(" available", style="dim")
    line.append("    ")
    line.append(
        f"{len(catalog.builtin_entries)} built-in"
        f" · {len(catalog.community_entries)} community"
        f" · {catalog.installed_count} installed",
        style="dim",
    )
    return line


def _cache_line(catalog: PluginCatalog, *, now: float) -> Text:
    age = _humanize_age(catalog.age_seconds(now))
    line = Text()
    if catalog.stale:
        line.append("⚠ ", style="yellow")
        line.append(
            f"Cache is stale (last updated {age}) · run {_REFRESH_COMMAND} to update",
            style="yellow",
        )
    else:
        line.append(f"Cached {age} · run {_REFRESH_COMMAND} to update", style="dim")
    return line


def _humanize_age(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"


__all__ = ["render_catalog_list"]
