"""Catalog and detail renderers for ``sase plugin list/show``."""

from __future__ import annotations

import time

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.plugins.catalog import (
    SASE_PLUGIN_ORG,
    PluginCatalog,
    PluginCatalogEntry,
)
from sase.plugins.render_common import (
    _AVAILABLE_GLYPH,
    _BUILTIN_STYLE,
    _COMMUNITY_STYLE,
    _EMPTY,
    _INSTALLED_CHECK,
    _INSTALLED_GLYPH,
    _NOT_INSTALLED_CROSS,
    _REFRESH_COMMAND,
    _UPDATE_GLYPH,
    build_incoming_commits_renderable,
    humanize_age,
)
from sase.updates.incoming_commits import IncomingCommits

#: The community section header *is* the warning, so the built-in/community
#: distinction is impossible to miss.
_COMMUNITY_WARNING = (
    "⚠ third-party, not maintained by sase-org — review before installing"
)


def render_catalog_list(
    catalog: PluginCatalog,
    *,
    verbose: bool = False,
    now: float | None = None,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin list`` catalog panel to *console*."""
    target = console or Console()
    target.print(build_catalog_list_panel(catalog, verbose=verbose, now=now))


def build_catalog_list_panel(
    catalog: PluginCatalog, *, verbose: bool = False, now: float | None = None
) -> Panel:
    """Console-free renderable for the ``sase plugin list`` catalog panel.

    Returns the same Rich :class:`~rich.panel.Panel` the CLI prints, so a TUI can
    display it verbatim for guaranteed list parity.
    """
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
    if catalog.updates_available:
        body.append(_updates_cta(catalog))
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
    table.add_column(no_wrap=True)  # update indicator
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
            _update_cell(entry),
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
        if entry.latest.version:
            return Text(f"latest v{entry.latest.version}", style="dim")
        if entry.latest.checked:
            return Text("latest unknown", style="dim")
        return Text(_EMPTY, style="dim")
    if entry.latest.source == "editable":
        return _dev_version_cell(entry)
    if entry.latest.source == "git":
        return Text("git", style="yellow")
    if entry.update_available:
        value = Text()
        value.append(f"v{info.version}", style="dim")
        value.append(" → ", style="dim")
        value.append(f"v{entry.latest.version}", style="cyan")
        return value
    if info.version:
        return Text(f"v{info.version}", style="green")
    return Text("installed", style="green")


def _update_cell(entry: PluginCatalogEntry) -> Text:
    if entry.update_available:
        return Text(_UPDATE_GLYPH, style="bold cyan")
    return Text("")


def _dev_version_cell(entry: PluginCatalogEntry) -> Text:
    latest = entry.latest
    current = latest.current_version or entry.installed.version
    value = Text()
    if entry.update_available and latest.version:
        value.append(_version_label(current) or "installed", style="dim")
        value.append(" → ", style="dim")
        value.append(f"v{latest.version}", style="cyan")
        value.append("   dev", style="dim")
        return value
    value.append(_version_label(current) or "editable", style="green")
    suffix = _dev_state_suffix(latest.state, update_available=False)
    if suffix:
        value.append(f"   {suffix}", style="dim")
    return value


def _version_label(version: str | None) -> str | None:
    return f"v{version}" if version else None


def _dev_state_suffix(state: str | None, *, update_available: bool) -> str:
    if update_available:
        return "dev update available"
    label = _dev_state_label(state)
    if label:
        return f"dev · {label}"
    return "dev"


def _dev_state_label(state: str | None) -> str:
    labels = {
        "current": "",
        "update_available": "update available",
        "dirty": "local changes",
        "diverged": "diverged",
        "detached": "detached HEAD",
        "no_upstream": "no upstream",
        "offline": "offline",
        "fetch_failed": "fetch failed",
        "unavailable": "unavailable",
    }
    return labels.get(state or "", state or "")


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
    line.append(" available   ", style="dim")
    line.append(_UPDATE_GLYPH, style="bold cyan")
    line.append(" update available", style="dim")
    line.append("    ")
    line.append(
        f"{len(catalog.builtin_entries)} built-in"
        f" · {len(catalog.community_entries)} community"
        f" · {catalog.installed_count} installed"
        f" · {catalog.updates_available} update available",
        style="dim",
    )
    return line


def _updates_cta(catalog: PluginCatalog) -> Text:
    line = Text()
    has_dev_update = any(
        entry.update_available and entry.latest.source == "editable"
        for entry in catalog.entries
    )
    command = "`sase update`" if has_dev_update else "`sase plugin update --all`"
    line.append(_UPDATE_GLYPH, style="bold cyan")
    line.append(
        f" {catalog.updates_available} update available · run ",
        style="cyan",
    )
    line.append(command, style="bold cyan")
    return line


def _cache_line(catalog: PluginCatalog, *, now: float) -> Text:
    age = humanize_age(catalog.age_seconds(now))
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


def render_catalog_show(
    entry: PluginCatalogEntry,
    *,
    catalog: PluginCatalog,
    now: float | None = None,
    console: Console | None = None,
) -> None:
    """Print the detailed single-plugin view for ``sase plugin show``."""
    target = console or Console()
    now = time.time() if now is None else now

    for warning in catalog.warnings:
        target.print(Text(f"⚠ {warning}", style="yellow"))
    if entry.is_community:
        target.print(build_community_warning_panel(entry))
    target.print(build_detail_panel(entry))
    target.print(_show_cache_line(entry, catalog, now=now))


def build_community_warning_panel(entry: PluginCatalogEntry) -> Panel:
    """Console-free renderable for a community plugin's prominent warning.

    Public so the TUI detail panel can lead community plugins with the exact
    same warning ``sase plugin show`` prints.
    """
    body = Text()
    body.append("This plugin is published by ", style=_COMMUNITY_STYLE)
    body.append(entry.owner or "an unknown owner", style=f"bold {_COMMUNITY_STYLE}")
    body.append(
        f", not the official `{SASE_PLUGIN_ORG}` org.\n",
        style=_COMMUNITY_STYLE,
    )
    body.append(
        "It is third-party software. Review its source before installing.",
        style=_COMMUNITY_STYLE,
    )
    return Panel(
        body,
        title=Text("⚠  COMMUNITY PLUGIN", style=f"bold {_COMMUNITY_STYLE}"),
        border_style=_COMMUNITY_STYLE,
    )


def build_detail_panel(
    entry: PluginCatalogEntry,
    *,
    incoming_commits: IncomingCommits | None = None,
    incoming_commits_loading: bool = False,
) -> Panel:
    """Console-free renderable for the ``sase plugin show`` detail panel.

    Public so the TUI detail panel can display the same ``show``-equivalent
    renderable, giving the TUI and the CLI visual parity for free.
    """
    border = _BUILTIN_STYLE if entry.is_builtin else _COMMUNITY_STYLE

    body: list[RenderableType] = [_kind_line(entry), Text("")]
    body.append(_detail_description(entry))
    if incoming_commits is not None or incoming_commits_loading:
        body.append(Text(""))
        body.append(
            build_incoming_commits_renderable(
                incoming_commits,
                loading=incoming_commits_loading,
            )
        )
    body.append(Text(""))
    body.append(_detail_rows(entry))
    if not entry.installed.installed:
        body.append(Text(""))
        body.append(_install_hint(entry))

    return Panel(Group(*body), title=_detail_title(entry), border_style=border)


def _detail_title(entry: PluginCatalogEntry) -> Text:
    title = Text()
    title.append(entry.name or entry.repo, style="bold")
    if entry.full_name:
        title.append(" · ", style="dim")
        title.append(entry.full_name, style="dim")
    return title


def _kind_line(entry: PluginCatalogEntry) -> Text:
    if entry.is_builtin:
        return Text("BUILT-IN (official)", style=f"bold {_BUILTIN_STYLE}")
    return Text("COMMUNITY (third-party)", style=f"bold {_COMMUNITY_STYLE}")


def _detail_description(entry: PluginCatalogEntry) -> Text:
    description = Text(entry.description or _EMPTY)
    if entry.archived:
        description.append("  (archived)", style="red")
    return description


def _detail_rows(entry: PluginCatalogEntry) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)  # label
    table.add_column()  # value

    table.add_row("Installed", _installed_value(entry))
    table.add_row("Latest", _latest_value(entry))
    table.add_row("Repository", Text(entry.url or _EMPTY, style="dim"))
    table.add_row("Homepage", Text(entry.homepage or _EMPTY, style="dim"))
    table.add_row("Topics", _topics_value(entry))
    table.add_row("Stars", _meta_value(entry))
    return table


def _installed_value(entry: PluginCatalogEntry) -> Text:
    info = entry.installed
    if not info.installed:
        value = Text()
        value.append(f"{_NOT_INSTALLED_CROSS}  not installed", style="dim")
        return value

    value = Text()
    value.append(f"{_INSTALLED_CHECK}  ", style="green")
    if entry.latest.source == "editable":
        current = entry.latest.current_version or info.version
        value.append(_version_label(current) or "editable", style="green")
        value.append("   (dev editable checkout)", style="dim")
        return value
    if entry.latest.source == "git":
        value.append("git", style="yellow")
        value.append("   (direct URL)", style="dim")
        return value
    value.append(f"v{info.version}" if info.version else "installed", style="green")
    if info.entry_point_groups:
        value.append(f"   ({', '.join(info.entry_point_groups)})", style="dim")
    return value


def _latest_value(entry: PluginCatalogEntry) -> Text:
    latest = entry.latest
    value = Text()
    if latest.source == "editable":
        if entry.update_available and latest.version:
            value.append(f"v{latest.version}", style="cyan")
            value.append(
                f"   {_UPDATE_GLYPH} {_dev_state_suffix(latest.state, update_available=True)} — run ",
                style="cyan",
            )
            value.append(
                "`sase update`",
                style="bold cyan",
            )
            return value
        value.append(_version_label(latest.version) or "unknown", style="dim")
        value.append(
            f"   {_dev_state_suffix(latest.state, update_available=False)}",
            style="dim",
        )
        return value
    if latest.source == "git":
        value.append("not compared", style="dim")
        value.append("   git install", style="yellow")
        return value
    if entry.update_available:
        value.append(f"v{latest.version}", style="cyan")
        value.append(f"   {_UPDATE_GLYPH} update available — run ", style="cyan")
        value.append(
            f"`sase plugin update {entry.name or entry.repo}`", style="bold cyan"
        )
        return value
    if latest.version:
        value.append(
            f"v{latest.version}", style="green" if entry.installed.installed else "dim"
        )
        if entry.installed.installed:
            value.append(f"   {_INSTALLED_CHECK} up to date", style="green")
        return value
    value.append("unknown", style="dim")
    if latest.error == "offline":
        value.append("   run without `--offline` or use `--refresh`", style="dim")
    elif latest.checked:
        value.append("   not available from the index right now", style="dim")
    return value


def _topics_value(entry: PluginCatalogEntry) -> Text:
    if not entry.topics:
        return Text(_EMPTY, style="dim")
    return Text(" · ".join(entry.topics), style="dim")


def _meta_value(entry: PluginCatalogEntry) -> Text:
    value = Text()
    value.append(str(entry.stars))
    value.append("      Updated  ", style="dim")
    value.append(entry.updated_at or _EMPTY)
    value.append("      License  ", style="dim")
    value.append(entry.license or _EMPTY)
    return value


def _install_hint(entry: PluginCatalogEntry) -> Text:
    name = entry.name or entry.repo
    hint = Text()
    hint.append("Not installed — run ", style="dim")
    hint.append(f"`sase plugin install {name}`", style="cyan")
    hint.append(" to add it to sase's environment.", style="dim")
    return hint


def _show_cache_line(
    entry: PluginCatalogEntry, catalog: PluginCatalog, *, now: float
) -> Text:
    age = humanize_age(catalog.age_seconds(now))
    command = f"`sase plugin show {entry.name or entry.repo} --refresh`"
    line = Text()
    if catalog.stale:
        line.append("⚠ ", style="yellow")
        line.append(
            f"Cache is stale (last updated {age}) · run {command} to update",
            style="yellow",
        )
    else:
        line.append(f"Cached {age} · run {command} to update", style="dim")
    return line


def render_show_not_found(
    query: str,
    suggestions: tuple[PluginCatalogEntry, ...],
    *,
    console: Console | None = None,
) -> None:
    """Print the "no such plugin" miss view with ranked suggestions."""
    target = console or Console(stderr=True)
    target.print(Text(f"No plugin named '{query}' in the catalog.", style="bold red"))
    if suggestions:
        target.print(Text("Did you mean one of these?", style="dim"))
        for entry in suggestions:
            line = Text("  • ", style="dim")
            line.append(entry.name, style="bold")
            if entry.full_name:
                line.append(f"  ({entry.full_name})", style="dim")
            target.print(line)
    else:
        target.print(
            Text("Run `sase plugin list` to see all known plugins.", style="dim")
        )
