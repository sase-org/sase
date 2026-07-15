"""Rich rendering for the ``sase update`` command (and shared by Phase 3).

The engine never prints; this module turns a parsed :class:`~sase.uv_tool.runner.
UvChangeSet` into a beautiful, copy-pasteable summary. It mirrors the ``sase
plugin`` catalog renderer's grammar — a single titled :class:`~rich.panel.Panel`
holding a borderless table, glyphs (``✓ · ✗ ⚠``) backed by explicit labels, and
green/cyan/yellow/dim styling — so color enhances but is never load-bearing.

:func:`summarize_update` is the pure seam: given the change set, the receipt's
known package set, and a current-version lookup, it produces an ordered
:class:`UpdateSummary` that both the Rich renderer and the ``--json`` payload
consume, so the two can never drift.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.uv_tool.receipt import ToolReceipt
from sase.uv_tool.runner import ChangeKind, UvChangeSet
from sase.version._utils import normalize_distribution_name

#: A package's place in sase's uv tool environment.
PackageRole = Literal["primary", "plugin", "dependency"]

#: Glyphs (never color alone) for each outcome. ``✗`` (red) marks a removal or a
#: fatal error and ``⚠`` (yellow) is reserved for non-fatal warnings, matching
#: the ``sase plugin`` catalog renderer's legend.
_UPDATED_GLYPH = "✓"
_UNCHANGED_GLYPH = "·"
_REMOVED_GLYPH = "✗"
_ERROR_GLYPH = "✗"

#: Em dash placeholder for an unknown version.
_EMPTY = "—"

_PRIMARY_PACKAGE = "sase"


@dataclass(frozen=True)
class UpdateOutcome:
    """What happened to one package across a ``sase update`` run.

    For an ``UNCHANGED`` package, ``new_version`` carries the current installed
    version (the "already current" value), and ``old_version`` is ``None``.
    """

    name: str
    role: PackageRole
    kind: ChangeKind
    old_version: str | None = None
    new_version: str | None = None

    @property
    def is_update(self) -> bool:
        """Whether this package was added or upgraded."""
        return self.kind in (ChangeKind.ADDED, ChangeKind.UPGRADED)


@dataclass(frozen=True)
class UpdateSummary:
    """The ordered, merged result of a ``sase update`` run."""

    outcomes: tuple[UpdateOutcome, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether any package was added, upgraded, or removed."""
        return any(o.kind is not ChangeKind.UNCHANGED for o in self.outcomes)

    @property
    def updated(self) -> tuple[UpdateOutcome, ...]:
        """Packages that were added or upgraded."""
        return tuple(o for o in self.outcomes if o.is_update)

    @property
    def removed(self) -> tuple[UpdateOutcome, ...]:
        """Packages that were removed."""
        return tuple(o for o in self.outcomes if o.kind is ChangeKind.REMOVED)

    @property
    def already_current(self) -> tuple[UpdateOutcome, ...]:
        """Known packages that did not change."""
        return tuple(o for o in self.outcomes if o.kind is ChangeKind.UNCHANGED)

    @property
    def primary_updated(self) -> bool:
        """Whether the primary ``sase`` package itself was updated."""
        return any(o.role == "primary" and o.is_update for o in self.outcomes)

    @property
    def updated_plugins(self) -> tuple[UpdateOutcome, ...]:
        """Injected plugins that were added or upgraded."""
        return tuple(o for o in self.updated if o.role == "plugin")

    @property
    def updated_dependencies(self) -> tuple[UpdateOutcome, ...]:
        """Transitive dependencies that were added or upgraded."""
        return tuple(o for o in self.updated if o.role == "dependency")


@dataclass(frozen=True)
class PlannedPackage:
    """A package that ``sase update`` would re-resolve, with its current version."""

    name: str
    role: PackageRole
    current_version: str | None = None


def summarize_update(
    change_set: UvChangeSet,
    receipt: ToolReceipt | None,
    *,
    current_version: Callable[[str], str | None],
) -> UpdateSummary:
    """Merge a uv change set with the receipt's known packages.

    Receipt packages (``sase`` first, then injected plugins in receipt order)
    lead the result so the user's own surface is highlighted; any further changed
    packages (transitive dependencies) follow. A receipt package absent from the
    change set is reported as ``UNCHANGED`` with its current version, looked up
    via *current_version* (reliable precisely because it did not change).
    """
    outcomes: list[UpdateOutcome] = []
    consumed: set[str] = set()

    if receipt is not None:
        outcomes.append(
            _outcome_for(receipt.primary.name, "primary", change_set, current_version)
        )
        consumed.add(normalize_distribution_name(receipt.primary.name))
        for plugin in receipt.deduped_injected_plugins():
            outcomes.append(
                _outcome_for(plugin.name, "plugin", change_set, current_version)
            )
            consumed.add(plugin.normalized_name)

    for change in change_set.changes:
        if normalize_distribution_name(change.name) in consumed:
            continue
        role: PackageRole = (
            "primary"
            if receipt is None
            and normalize_distribution_name(change.name)
            == normalize_distribution_name(_PRIMARY_PACKAGE)
            else "dependency"
        )
        outcomes.append(
            UpdateOutcome(
                name=change.name,
                role=role,
                kind=change.kind,
                old_version=change.old_version,
                new_version=change.new_version,
            )
        )

    return UpdateSummary(tuple(outcomes))


def summarize_planned_update(
    change_set: UvChangeSet,
    packages: tuple[PlannedPackage, ...],
) -> UpdateSummary:
    """Merge a uv change set with an explicit managed target list.

    Editable comprehensive updates do not have a managed primary requirement
    to use as a summary anchor. Their planned targets (notably a transitive
    ``sase-core-rs`` wheel) provide the stable order and unchanged versions.
    """
    outcomes: list[UpdateOutcome] = []
    consumed: set[str] = set()
    for package in packages:
        change = change_set.get(package.name)
        if change is None:
            outcomes.append(
                UpdateOutcome(
                    name=package.name,
                    role=package.role,
                    kind=ChangeKind.UNCHANGED,
                    new_version=package.current_version,
                )
            )
        else:
            outcomes.append(
                UpdateOutcome(
                    name=package.name,
                    role=package.role,
                    kind=change.kind,
                    old_version=change.old_version,
                    new_version=change.new_version,
                )
            )
        consumed.add(normalize_distribution_name(package.name))

    for change in change_set.changes:
        if normalize_distribution_name(change.name) in consumed:
            continue
        outcomes.append(
            UpdateOutcome(
                name=change.name,
                role="dependency",
                kind=change.kind,
                old_version=change.old_version,
                new_version=change.new_version,
            )
        )
    return UpdateSummary(tuple(outcomes))


def _outcome_for(
    name: str,
    role: PackageRole,
    change_set: UvChangeSet,
    current_version: Callable[[str], str | None],
) -> UpdateOutcome:
    change = change_set.get(name)
    if change is not None:
        return UpdateOutcome(
            name=name,
            role=role,
            kind=change.kind,
            old_version=change.old_version,
            new_version=change.new_version,
        )
    return UpdateOutcome(
        name=name,
        role=role,
        kind=ChangeKind.UNCHANGED,
        new_version=current_version(name),
    )


def render_update_result(
    summary: UpdateSummary,
    *,
    elapsed: float | None = None,
    quiet: bool = False,
    console: Console | None = None,
) -> None:
    """Print the ``sase update`` result panel (or a one-liner when *quiet*)."""
    target = console or Console()

    if quiet:
        target.print(_quiet_summary_line(summary, elapsed))
        return

    if not summary.changed:
        target.print(_up_to_date_panel())
        return

    body: list[RenderableType] = [_outcomes_table(summary)]
    body.append(Text(""))
    body.append(_summary_line(summary, elapsed))
    body.append(
        Text(
            "Restart running sase agents to pick up the new version.",
            style="dim",
        )
    )
    target.print(Panel(Group(*body), title="SASE Update", border_style="cyan"))


def render_update_dry_run(
    argv: list[str],
    packages: tuple[PlannedPackage, ...],
    *,
    console: Console | None = None,
) -> None:
    """Print the ``sase update --dry-run`` preview: the uv argv plus the set."""
    target = console or Console()

    body: list[RenderableType] = []
    command = Text()
    command.append("Would run  ", style="dim")
    command.append(" ".join(argv), style="cyan")
    body.append(command)
    body.append(Text(""))

    if packages:
        body.append(_planned_table(packages))
    else:
        body.append(Text("No packages found in the uv receipt.", style="dim"))

    body.append(Text(""))
    note = Text()
    note.append("Dry run — nothing was changed. Re-run as ", style="dim")
    note.append("sase update", style="cyan")
    note.append(" to upgrade.", style="dim")
    body.append(note)

    target.print(
        Panel(Group(*body), title="SASE Update (dry run)", border_style="cyan")
    )


def render_uv_tool_error(message: str, *, console: Console | None = None) -> None:
    """Print an engine error message to *console* (stderr by default)."""
    target = console or Console(stderr=True)
    line = Text()
    line.append(f"{_ERROR_GLYPH} ", style="red")
    line.append(message, style="red")
    target.print(line)


def _outcomes_table(summary: UpdateSummary) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(no_wrap=True)  # glyph
    table.add_column(style="bold", no_wrap=True)  # name
    table.add_column(no_wrap=True)  # version transition
    table.add_column()  # note

    for outcome in summary.outcomes:
        table.add_row(
            _glyph(outcome),
            Text(outcome.name),
            _version_cell(outcome),
            _note_cell(outcome),
        )
    return table


def _planned_table(packages: tuple[PlannedPackage, ...]) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False, padding=(0, 2))
    table.add_column(style="bold", no_wrap=True)  # name
    table.add_column(no_wrap=True)  # current version
    table.add_column()  # role label

    for package in packages:
        version = package.current_version
        table.add_row(
            Text(package.name),
            Text(f"v{version}" if version else _EMPTY, style="dim"),
            Text(_role_label(package.role), style="dim"),
        )
    return table


def _glyph(outcome: UpdateOutcome) -> Text:
    if outcome.is_update:
        return Text(_UPDATED_GLYPH, style="green")
    if outcome.kind is ChangeKind.REMOVED:
        return Text(_REMOVED_GLYPH, style="red")
    return Text(_UNCHANGED_GLYPH, style="dim")


def _version_cell(outcome: UpdateOutcome) -> Text:
    if outcome.kind is ChangeKind.UPGRADED:
        cell = Text()
        cell.append(outcome.old_version or _EMPTY, style="dim")
        cell.append(" → ", style="dim")
        cell.append(outcome.new_version or _EMPTY, style="green")
        return cell
    if outcome.kind is ChangeKind.ADDED:
        return Text(outcome.new_version or _EMPTY, style="green")
    if outcome.kind is ChangeKind.REMOVED:
        return Text(outcome.old_version or _EMPTY, style="dim")
    return Text(outcome.new_version or _EMPTY, style="dim")


def _note_cell(outcome: UpdateOutcome) -> Text:
    if outcome.kind is ChangeKind.ADDED:
        return Text("(new)", style="dim")
    if outcome.kind is ChangeKind.REMOVED:
        return Text("(removed)", style="red")
    if outcome.kind is ChangeKind.UNCHANGED:
        return Text("(already current)", style="dim")
    return Text("")


def _up_to_date_panel() -> Panel:
    body = Text()
    body.append(f"{_UPDATED_GLYPH} ", style="green")
    body.append("Already up to date.", style="green")
    body.append(
        "\nsase and all installed plugins are at their latest versions.", style="dim"
    )
    return Panel(body, title="SASE Update", border_style="cyan")


def _summary_line(summary: UpdateSummary, elapsed: float | None) -> Text:
    subjects: list[str] = []
    if summary.primary_updated:
        subjects.append("sase")
    plugin_count = len(summary.updated_plugins)
    if plugin_count:
        subjects.append(f"{plugin_count} {_plural(plugin_count, 'plugin')}")

    dep_count = len(summary.updated_dependencies)
    if subjects:
        subject = " + ".join(subjects)
        if dep_count:
            subject += f" (+{dep_count} {_plural(dep_count, 'dependency')})"
    elif dep_count:
        subject = f"{dep_count} {_plural(dep_count, 'dependency')}"
    else:
        subject = "packages"

    line = Text()
    line.append("Updated ", style="green")
    line.append(subject, style="bold green")
    if elapsed is not None:
        line.append(f" in {_humanize_duration(elapsed)}", style="green")

    current_count = len(summary.already_current)
    if current_count:
        line.append(f" · {current_count} already current", style="dim")
    removed_count = len(summary.removed)
    if removed_count:
        line.append(
            f" · {removed_count} {_plural(removed_count, 'package')} removed",
            style="dim",
        )
    return line


def _quiet_summary_line(summary: UpdateSummary, elapsed: float | None) -> Text:
    if not summary.changed:
        return Text("Already up to date.", style="dim")
    return _summary_line(summary, elapsed)


def _role_label(role: PackageRole) -> str:
    if role == "primary":
        return "sase core"
    if role == "plugin":
        return "plugin"
    return "dependency"


def _plural(count: int, singular: str) -> str:
    if count == 1:
        return singular
    if singular.endswith("y"):
        return f"{singular[:-1]}ies"
    return f"{singular}s"


def _humanize_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m{rest:02d}s"


__all__ = [
    "PackageRole",
    "PlannedPackage",
    "UpdateOutcome",
    "UpdateSummary",
    "render_update_dry_run",
    "render_update_result",
    "render_uv_tool_error",
    "summarize_update",
    "summarize_planned_update",
]
