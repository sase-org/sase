"""Rich rendering for the ``sase plugin`` commands.

Phase 2 renders the ``sase plugin list`` catalog: a single titled panel holding a
built-in section, a community section (led by an unmissable warning), and a footer
with a glyph legend, counts, and the cache-age + refresh affordance. Phase 3 adds
the ``sase plugin show <plugin_name>`` detail view: a single-plugin panel, a
prominent community-warning panel above it for third-party plugins, and a
ranked "did you mean…?" miss view. Color enhances but is never load-bearing —
glyphs and explicit labels carry the meaning so the output stays legible when
copied into an agent chat or a no-color terminal.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.plugins.catalog import (
    SASE_PLUGIN_ORG,
    PluginCatalog,
    PluginCatalogEntry,
)
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from sase.version._utils import normalize_distribution_name

#: Glyphs (never color alone) for installed vs. available plugins.
_INSTALLED_GLYPH = "●"
_AVAILABLE_GLYPH = "○"
_UPDATE_GLYPH = "↑"

#: Glyphs (never color alone) for the ``show`` installed/not-installed row.
_INSTALLED_CHECK = "✓"
_NOT_INSTALLED_CROSS = "✗"

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
        return Text("editable", style="yellow")
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
    line.append(_UPDATE_GLYPH, style="bold cyan")
    line.append(
        f" {catalog.updates_available} update available · run ",
        style="cyan",
    )
    line.append("`sase plugin update --all`", style="bold cyan")
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


def _humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"


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


# --------------------------------------------------------------------------- #
# ``sase plugin show <plugin_name>``
# --------------------------------------------------------------------------- #


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
        target.print(_community_warning_panel(entry))
    target.print(_detail_panel(entry))
    target.print(_show_cache_line(entry, catalog, now=now))


def _community_warning_panel(entry: PluginCatalogEntry) -> Panel:
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


def _detail_panel(entry: PluginCatalogEntry) -> Panel:
    border = _BUILTIN_STYLE if entry.is_builtin else _COMMUNITY_STYLE

    body: list[RenderableType] = [_kind_line(entry), Text("")]
    body.append(_detail_description(entry))
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
        value.append("editable", style="yellow")
        value.append("   (local checkout)", style="dim")
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
        value.append("not compared", style="dim")
        value.append("   editable install", style="yellow")
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
    age = _humanize_age(catalog.age_seconds(now))
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


# --------------------------------------------------------------------------- #
# ``sase plugin install`` / ``sase plugin update`` results
# --------------------------------------------------------------------------- #

#: Result glyphs (never color alone), mirroring the ``sase update`` renderer.
_CHANGED_GLYPH = "✓"
_UNCHANGED_GLYPH = "·"


def _no_version(_name: str) -> str | None:
    """Default current-version lookup: unknown."""
    return None


def render_install_result(
    *,
    dist_name: str,
    short_name: str,
    change_set: UvChangeSet,
    groups: tuple[str, ...] = (),
    elapsed: float | None = None,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin install`` success panel."""
    target = console or Console()
    change = change_set.get(dist_name)
    deps = _other_changes(change_set, dist_name)

    body: list[RenderableType] = [_result_table((change or _added(dist_name),))]
    if groups:
        contributes = Text("  contributes  ", style="dim")
        contributes.append(", ".join(groups), style="green")
        body.append(contributes)

    body.append(Text(""))
    body.append(_install_summary_line(short_name, len(deps), elapsed))
    body.append(Text("Restart running sase agents to load the plugin.", style="dim"))
    target.print(Panel(Group(*body), title="Plugin Installed", border_style="cyan"))


def render_install_already_installed(
    *,
    dist_name: str,
    short_name: str,
    console: Console | None = None,
) -> None:
    """Print the idempotent "already installed" panel and exit success."""
    target = console or Console()
    body = Text()
    body.append(f"{_UNCHANGED_GLYPH} ", style="dim")
    body.append(dist_name, style="bold")
    body.append(" is already installed.", style="dim")
    body.append("\nRun ", style="dim")
    body.append(f"`sase plugin update {short_name}`", style="cyan")
    body.append(" to upgrade it to the latest version.", style="dim")
    target.print(Panel(body, title="Plugin Installed", border_style="cyan"))


def render_install_dry_run(
    *,
    argv: list[str],
    short_name: str,
    source: str,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin install --dry-run`` preview."""
    target = console or Console()
    body: list[RenderableType] = []
    command = Text()
    command.append("Would run  ", style="dim")
    command.append(" ".join(argv), style="cyan")
    body.append(command)
    body.append(Text(""))

    plan = Text()
    plan.append("Installs  ", style="dim")
    plan.append(short_name, style="bold")
    plan.append(f"  (from {source})", style="dim")
    body.append(plan)

    body.append(Text(""))
    note = Text()
    note.append("Dry run — nothing was changed. Re-run as ", style="dim")
    note.append(f"sase plugin install {short_name}", style="cyan")
    note.append(" to install.", style="dim")
    body.append(note)
    target.print(
        Panel(Group(*body), title="Plugin Install (dry run)", border_style="cyan")
    )


def render_plugin_update_result(
    *,
    change_set: UvChangeSet,
    dist_names: tuple[str, ...],
    all_plugins: bool = False,
    elapsed: float | None = None,
    current_version: Callable[[str], str | None] = _no_version,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin update`` result panel."""
    target = console or Console()
    changes = tuple(
        change_set.get(name) or _unchanged(name, current_version(name))
        for name in dist_names
    )
    if not any(c.kind is not ChangeKind.UNCHANGED for c in changes):
        target.print(_plugins_up_to_date_panel(all_plugins))
        return

    body: list[RenderableType] = [_result_table(changes)]
    body.append(Text(""))
    body.append(_plugin_update_summary_line(changes, elapsed))
    body.append(
        Text("Restart running sase agents to pick up the new version.", style="dim")
    )
    target.print(Panel(Group(*body), title="Plugin Update", border_style="cyan"))


def render_plugin_update_dry_run(
    *,
    argv: list[str],
    dist_names: tuple[str, ...],
    all_plugins: bool = False,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin update --dry-run`` preview."""
    target = console or Console()
    body: list[RenderableType] = []
    command = Text()
    command.append("Would run  ", style="dim")
    command.append(" ".join(argv), style="cyan")
    body.append(command)
    body.append(Text(""))

    subject = "every installed plugin" if all_plugins else None
    plan = Text()
    plan.append("Upgrades  ", style="dim")
    plan.append(subject or ", ".join(dist_names), style="bold")
    plan.append("  (sase core stays pinned)", style="dim")
    body.append(plan)

    body.append(Text(""))
    body.append(Text("Dry run — nothing was changed.", style="dim"))
    target.print(
        Panel(Group(*body), title="Plugin Update (dry run)", border_style="cyan")
    )


def render_plugin_not_installed(
    *,
    short_name: str,
    console: Console | None = None,
) -> None:
    """Print the "plugin is not installed" miss view for ``update``."""
    target = console or Console(stderr=True)
    line = Text()
    line.append(f"{_NOT_INSTALLED_CROSS} ", style="red")
    line.append(short_name, style="bold")
    line.append(" is not installed.", style="red")
    target.print(line)
    hint = Text("Run ", style="dim")
    hint.append(f"`sase plugin install {short_name}`", style="cyan")
    hint.append(" to add it first.", style="dim")
    target.print(hint)


def render_no_plugins_installed(*, console: Console | None = None) -> None:
    """Print the "no plugins to update" panel for ``update --all``."""
    target = console or Console()
    body = Text()
    body.append(f"{_UNCHANGED_GLYPH} ", style="dim")
    body.append("No plugins are installed.", style="dim")
    body.append("\nRun ", style="dim")
    body.append("`sase plugin list`", style="cyan")
    body.append(" to discover plugins, then ", style="dim")
    body.append("`sase plugin install <plugin>`", style="cyan")
    body.append(".", style="dim")
    target.print(Panel(body, title="Plugin Update", border_style="cyan"))


def _result_table(changes: tuple[UvPackageChange, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)  # glyph
    table.add_column(style="bold", no_wrap=True)  # name
    table.add_column(no_wrap=True)  # version transition
    table.add_column()  # note
    for change in changes:
        table.add_row(
            _result_glyph(change),
            Text(change.name),
            _result_version_cell(change),
            _result_note_cell(change),
        )
    return table


def _result_glyph(change: UvPackageChange) -> Text:
    if change.kind is ChangeKind.UNCHANGED:
        return Text(_UNCHANGED_GLYPH, style="dim")
    if change.kind is ChangeKind.REMOVED:
        return Text(_NOT_INSTALLED_CROSS, style="red")
    return Text(_CHANGED_GLYPH, style="green")


def _result_version_cell(change: UvPackageChange) -> Text:
    if change.kind is ChangeKind.UPGRADED:
        cell = Text()
        cell.append(change.old_version or _EMPTY, style="dim")
        cell.append(" → ", style="dim")
        cell.append(change.new_version or _EMPTY, style="green")
        return cell
    if change.kind is ChangeKind.ADDED:
        return Text(change.new_version or _EMPTY, style="green")
    if change.kind is ChangeKind.UNCHANGED:
        return Text(change.old_version or _EMPTY, style="dim")
    return Text(change.old_version or _EMPTY, style="dim")


def _result_note_cell(change: UvPackageChange) -> Text:
    if change.kind is ChangeKind.ADDED:
        return Text("(installed)", style="dim")
    if change.kind is ChangeKind.UNCHANGED:
        return Text("(already current)", style="dim")
    if change.kind is ChangeKind.REMOVED:
        return Text("(removed)", style="red")
    return Text("")


def _install_summary_line(
    short_name: str, dep_count: int, elapsed: float | None
) -> Text:
    line = Text()
    line.append("Installed ", style="green")
    line.append(short_name, style="bold green")
    if elapsed is not None:
        line.append(f" in {_humanize_duration(elapsed)}", style="green")
    if dep_count:
        line.append(f" · {dep_count} {_plural_dep(dep_count)} resolved", style="dim")
    return line


def _plugin_update_summary_line(
    changes: tuple[UvPackageChange, ...], elapsed: float | None
) -> Text:
    upgraded = sum(1 for c in changes if c.kind is ChangeKind.UPGRADED)
    current = sum(1 for c in changes if c.kind is ChangeKind.UNCHANGED)
    line = Text()
    line.append("Updated ", style="green")
    line.append(f"{upgraded} {_plural_plugin(upgraded)}", style="bold green")
    if elapsed is not None:
        line.append(f" in {_humanize_duration(elapsed)}", style="green")
    if current:
        line.append(f" · {current} already current", style="dim")
    return line


def _plugins_up_to_date_panel(all_plugins: bool) -> Panel:
    subject = "All installed plugins are" if all_plugins else "The plugin is"
    body = Text()
    body.append(f"{_CHANGED_GLYPH} ", style="green")
    body.append("Already up to date.", style="green")
    body.append(f"\n{subject} at the latest version.", style="dim")
    return Panel(body, title="Plugin Update", border_style="cyan")


def _other_changes(
    change_set: UvChangeSet, dist_name: str
) -> tuple[UvPackageChange, ...]:
    key = normalize_distribution_name(dist_name)
    return tuple(
        change
        for change in change_set.changes
        if normalize_distribution_name(change.name) != key
        and change.kind is not ChangeKind.UNCHANGED
    )


def _added(dist_name: str) -> UvPackageChange:
    return UvPackageChange(name=dist_name, kind=ChangeKind.ADDED)


def _unchanged(name: str, version: str | None) -> UvPackageChange:
    return UvPackageChange(name=name, kind=ChangeKind.UNCHANGED, old_version=version)


def _plural_plugin(count: int) -> str:
    return "plugin" if count == 1 else "plugins"


def _plural_dep(count: int) -> str:
    return "dependency" if count == 1 else "dependencies"


__all__ = [
    "render_catalog_list",
    "render_catalog_show",
    "render_install_already_installed",
    "render_install_dry_run",
    "render_install_result",
    "render_no_plugins_installed",
    "render_plugin_not_installed",
    "render_plugin_update_dry_run",
    "render_plugin_update_result",
    "render_show_not_found",
]
