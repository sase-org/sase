"""Install and update result renderers for ``sase plugin`` commands."""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.plugins.render_common import (
    _CHANGED_GLYPH,
    _EMPTY,
    _NOT_INSTALLED_CROSS,
    _UNCHANGED_GLYPH,
    humanize_duration,
)
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from sase.version._utils import normalize_distribution_name


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


def render_plugin_uninstall_result(
    *,
    change_set: UvChangeSet,
    dist_name: str,
    short_name: str,
    elapsed: float | None = None,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin uninstall`` success panel."""
    target = console or Console()
    change = change_set.get(dist_name) or _removed(dist_name)
    body: list[RenderableType] = [_result_table((change,))]
    body.append(Text(""))
    body.append(_uninstall_summary_line(short_name, elapsed))
    body.append(Text("Restart running sase agents to unload the plugin.", style="dim"))
    target.print(Panel(Group(*body), title="Plugin Uninstalled", border_style="cyan"))


def render_plugin_uninstall_dry_run(
    *,
    argv: list[str],
    short_name: str,
    console: Console | None = None,
) -> None:
    """Print the ``sase plugin uninstall --dry-run`` preview."""
    target = console or Console()
    body: list[RenderableType] = []
    command = Text()
    command.append("Would run  ", style="dim")
    command.append(" ".join(argv), style="cyan")
    body.append(command)
    body.append(Text(""))

    plan = Text()
    plan.append("Removes  ", style="dim")
    plan.append(short_name, style="bold")
    plan.append("  (other plugins stay installed)", style="dim")
    body.append(plan)

    body.append(Text(""))
    note = Text()
    note.append("Dry run — nothing was changed. Re-run as ", style="dim")
    note.append(f"sase plugin uninstall {short_name}", style="cyan")
    note.append(" to remove it.", style="dim")
    body.append(note)
    target.print(
        Panel(Group(*body), title="Plugin Uninstall (dry run)", border_style="cyan")
    )


def render_plugin_uninstall_not_installed(
    *,
    short_name: str,
    console: Console | None = None,
) -> None:
    """Print the idempotent "already absent" panel for ``uninstall`` (exit 0)."""
    target = console or Console()
    body = Text()
    body.append(f"{_UNCHANGED_GLYPH} ", style="dim")
    body.append(short_name, style="bold")
    body.append(" is not installed — nothing to uninstall.", style="dim")
    target.print(Panel(body, title="Plugin Uninstall", border_style="cyan"))


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
        line.append(f" in {humanize_duration(elapsed)}", style="green")
    if dep_count:
        line.append(f" · {dep_count} {_plural_dep(dep_count)} resolved", style="dim")
    return line


def _uninstall_summary_line(short_name: str, elapsed: float | None) -> Text:
    line = Text()
    line.append("Uninstalled ", style="green")
    line.append(short_name, style="bold green")
    if elapsed is not None:
        line.append(f" in {humanize_duration(elapsed)}", style="green")
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
        line.append(f" in {humanize_duration(elapsed)}", style="green")
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


def _removed(dist_name: str) -> UvPackageChange:
    return UvPackageChange(name=dist_name, kind=ChangeKind.REMOVED)


def _unchanged(name: str, version: str | None) -> UvPackageChange:
    return UvPackageChange(name=name, kind=ChangeKind.UNCHANGED, old_version=version)


def _plural_plugin(count: int) -> str:
    return "plugin" if count == 1 else "plugins"


def _plural_dep(count: int) -> str:
    return "dependency" if count == 1 else "dependencies"
