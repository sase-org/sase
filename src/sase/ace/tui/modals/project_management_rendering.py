"""Rendering and status helpers for the project management modal."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from rich.text import Text

from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.main.project_handler import ProjectLifecycleBlockedError

# Shared column widths so the column header and every row stay perfectly
# aligned. This is the single source of truth feeding both ``column_header_text``
# and ``record_label`` — change a width here and both move together.
_MARK_WIDTH = 4
_NAME_WIDTH = 28
_STATE_WIDTH = 12
_ALIASES_WIDTH = 15
_CLAIMS_WIDTH = 9
_LAUNCH_WIDTH = 9
_WARN_WIDTH = 7
_WORKSPACE_WIDTH = 38

_STATE_TABS: tuple[str, ...] = ("active", "sibling", "inactive", "all")


def _warning_count(record: ProjectRecordWire) -> int:
    return len(record.warnings) + len(record.parse_warnings)


def _short_path(path: str | None, *, max_len: int = 46) -> str:
    if not path:
        return "-"
    text = str(Path(path).expanduser())
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3) :]


def _state_style(state: str) -> str:
    if state == "active":
        return "bold #00D7AF"
    if state == "inactive":
        return "bold #FFD700"
    if state == "sibling":
        return "bold #87D7FF"
    return "bold"


def _launch_label(record: ProjectRecordWire) -> str:
    return "yes" if record.launchable and record.state == "active" else "no"


def _aliases_label(record: ProjectRecordWire) -> str:
    if not record.aliases:
        return "-"
    joined = ", ".join(record.aliases)
    if len(joined) <= _ALIASES_WIDTH:
        return joined
    count = f"{len(record.aliases)} aliases"
    if len(count) <= _ALIASES_WIDTH:
        return count
    if _ALIASES_WIDTH <= 3:
        return joined[:_ALIASES_WIDTH]
    return joined[: _ALIASES_WIDTH - 3] + "..."


def _project_label(record: ProjectRecordWire) -> str:
    display = effective_project_name(record)
    if display == record.project_name:
        return display
    return f"{display} ({record.project_name})"


def column_header_text() -> Text:
    """Dim/bold header row labeling the project columns.

    Padded with the same shared width constants as :func:`record_label` so the
    header sits directly above and aligned with each row.
    """
    text = Text(style="bold dim")
    text.append(" " * _MARK_WIDTH)
    text.append(f"{'NAME':<{_NAME_WIDTH}}")
    text.append(f"{'STATE':<{_STATE_WIDTH}}")
    text.append(f"{'ALIASES':<{_ALIASES_WIDTH}}")
    text.append(f"{'CLAIMS':<{_CLAIMS_WIDTH}}")
    text.append(f"{'LAUNCH':<{_LAUNCH_WIDTH}}")
    text.append(f"{'WARN':<{_WARN_WIDTH}}")
    text.append("WORKSPACE")
    return text


def record_label(record: ProjectRecordWire, marked_projects: set[str]) -> Text:
    text = Text()
    inactive = record.state == "inactive"
    if record.project_name in marked_projects:
        text.append("[✓]", style="bold #00D700")
        text.append("!" if inactive else " ", style="bold #FFD700")
    elif inactive:
        text.append("!   ", style="bold #FFD700")
    else:
        text.append(" " * _MARK_WIDTH)
    label = _project_label(record)
    text.append(f"{label:<{_NAME_WIDTH}.{_NAME_WIDTH}}", style="bold")
    badge = f"● {record.state}"
    text.append(
        f"{badge:<{_STATE_WIDTH}.{_STATE_WIDTH}}",
        style=_state_style(record.state),
    )
    alias_style = "#D7AF5F" if record.aliases else "dim"
    text.append(
        f"{_aliases_label(record):<{_ALIASES_WIDTH}.{_ALIASES_WIDTH}}",
        style=alias_style,
    )
    text.append(f"{record.active_claim_count:<{_CLAIMS_WIDTH}}")
    text.append(f"{_launch_label(record):<{_LAUNCH_WIDTH}}")
    warnings = _warning_count(record)
    if warnings:
        text.append(f"{warnings:<{_WARN_WIDTH}}", style="bold red")
    else:
        text.append(f"{'-':<{_WARN_WIDTH}}", style="dim")
    text.append(
        _short_path(record.workspace_dir, max_len=_WORKSPACE_WIDTH),
        style="dim",
    )
    return text


def state_tabs_text(state_filter: str) -> Text:
    """Segmented ``active / sibling / inactive / all`` filter tabs.

    The active filter is uppercased and reverse-highlighted; the rest are dim.
    Mirrors the header tabs used by the notification modal so the current
    filter is obvious at a glance instead of buried in a text summary.
    """
    text = Text()
    for index, name in enumerate(_STATE_TABS):
        if index:
            text.append("   ", style="dim")
        if name == state_filter:
            text.append(f" {name.upper()} ", style="bold reverse")
        else:
            text.append(name, style="dim")
    return text


def summary_text(
    records: Sequence[ProjectRecordWire],
    text_filter: str,
    status_message: str,
    marked_projects: set[str],
    show_inactive_projects: bool,
) -> Text:
    counts: dict[str, int] = {"active": 0, "inactive": 0, "sibling": 0}
    for record in records:
        if record.state in counts:
            counts[record.state] += 1
    text = Text()
    text.append(
        " ".join(
            (
                f"all:{len(records)}",
                f"active:{counts['active']}",
                f"sibling:{counts['sibling']}",
                f"inactive:{counts['inactive']}",
            )
        ),
        style="dim",
    )
    mark_count = len(marked_projects)
    text.append("  ·  marked:", style="dim")
    text.append(
        str(mark_count),
        style="bold #00D700" if mark_count else "dim",
    )
    if text_filter:
        text.append(f"  ·  search:{text_filter}", style="dim")
    text.append("  ·  inactive rows:", style="dim")
    text.append(
        "visible" if show_inactive_projects else "hidden",
        style="#FFD700" if show_inactive_projects else "dim",
    )
    if status_message:
        text.append(f"  ·  {status_message}", style="#87D7FF")
    return text


def _action_hints(show_inactive_projects: bool) -> str:
    """Shared keybinding hint string (no close / tab-switch affordance)."""
    inactive_action = "hide inactive" if show_inactive_projects else "show inactive"
    return (
        "j/k navigate  / filter  [ / ] state  Enter highlighted  "
        f"Ctrl+X {inactive_action}  m mark  u unmark all  e edit  A aliases  a activate  d deactivate  "
        "Ctrl+D delete  F force after block  R reload"
    )


def hints_text(marked_projects: set[str], show_inactive_projects: bool) -> str:
    """Single-line hints for the Projects pane.

    Reuses the modal's action hint string and always ends with the
    tab-switch / close affordance so the Admin Center tab teaches its own
    navigation now that there is no dedicated ``,p`` shortcut.
    """
    base = _action_hints(show_inactive_projects)
    mark_count = len(marked_projects)
    if mark_count:
        base = f"{base}  marked:{mark_count} (a/d/Ctrl+D target marked set)"
    return f"{base}  Tab/Shift+Tab switch tab   q close"


def detail_text(
    record: ProjectRecordWire | None,
    marked_projects: set[str],
) -> Text:
    text = Text()
    if record is None:
        text.append("No project selected", style="dim")
        return text

    source = "explicit" if record.state_explicit else "defaulted"
    launch = "yes" if record.launchable and record.state == "active" else "no"
    display = effective_project_name(record)
    text.append(display, style="bold")
    if display != record.project_name:
        text.append(f" ({record.project_name})", style="dim")
    text.append("   ")
    text.append(f"● {record.state}", style=_state_style(record.state))
    text.append(f" ({source})", style="dim")
    text.append("\n\n")
    text.append("Project file:  ", style="dim")
    text.append(str(record.project_file))
    text.append("\nWorkspace:     ", style="dim")
    text.append(_short_path(record.workspace_dir, max_len=72))
    text.append("\nActive claims: ", style="dim")
    text.append(str(record.active_claim_count))
    text.append("    Launchable: ", style="dim")
    text.append(launch)
    text.append("\nAliases:       ", style="dim")
    text.append(", ".join(record.aliases) if record.aliases else "-")
    if marked_projects:
        row_state = "marked" if record.project_name in marked_projects else "not marked"
        text.append(
            "\nMarked set: "
            f"{len(marked_projects)} project(s); "
            "a/d/Ctrl+D target marked projects; "
            f"this row is {row_state}.",
            style="#87D7FF",
        )
    warnings = [*record.warnings, *record.parse_warnings]
    if warnings:
        text.append("\nWarnings:", style="bold red")
        for warning in warnings:
            text.append(f"\n  - {warning}", style="red")
    if record.state != "active":
        text.append(
            f"\nHint: press a or Enter to reactivate {display}.",
            style="#87D7FF",
        )
    return text


def truncated_project_lines(projects: Sequence[str]) -> list[str]:
    limit = 8
    lines = [f"  - {project}" for project in projects[:limit]]
    remaining = len(projects) - limit
    if remaining > 0:
        lines.append(f"  ... and {remaining} more")
    return lines


def force_state_change_message(projects: Sequence[str], state: str) -> str:
    if len(projects) == 1:
        return f"Force {projects[0]} to {state} even though live work was found?"
    lines = [
        f"Force {len(projects)} projects to {state} even though live work was found?",
        "",
    ]
    lines.extend(truncated_project_lines(projects))
    return "\n".join(lines)


def bulk_delete_message(
    records: Sequence[ProjectRecordWire],
    project_dir_for: Callable[[ProjectRecordWire], Path],
) -> str:
    lines = [
        f"Delete SASE project directories for {len(records)} marked projects?",
        "",
        "Projects:",
    ]
    limit = 8
    for record in records[:limit]:
        lines.append(f"  - {_project_label(record)}: {project_dir_for(record)}")
    remaining = len(records) - limit
    if remaining > 0:
        lines.append(f"  ... and {remaining} more")
    lines.extend(
        [
            "",
            "This removes project specs, project-local config, artifacts, "
            "and other SASE state. It cannot be undone.",
            "",
            "Workspace checkouts are not deleted.",
        ]
    )
    return "\n".join(lines)


def state_change_status(
    records: Sequence[ProjectRecordWire],
    state: str,
    *,
    bulk: bool,
    skipped: Sequence[str],
    successes: Sequence[ProjectRecordWire],
    blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
    failed: Sequence[tuple[str, Exception]],
) -> str:
    if not bulk:
        if successes:
            updated = successes[0]
            return f"{effective_project_name(updated)} -> {updated.state}"
        if skipped:
            return f"{effective_project_name(records[0])} is already {state}"
        if blocked:
            return f"Blocked: {blocked[0][1]}. Press F to force."
        if failed:
            return f"Failed: {failed[0][1]}"
        return "No project selected"

    parts: list[str] = []
    if successes:
        parts.append(f"{len(successes)} changed to {state}")
    if skipped:
        parts.append(f"{len(skipped)} already {state}")
    if blocked:
        parts.append(f"{len(blocked)} blocked")
    if failed:
        parts.append(f"{len(failed)} failed")
    if not parts:
        return "No marked projects changed"

    status = "Marked projects: " + ", ".join(parts)
    if blocked:
        blocked_names = ", ".join(project for project, _exc in blocked[:3])
        if len(blocked) > 3:
            blocked_names += f", ... +{len(blocked) - 3}"
        status += f". Press F to force blocked: {blocked_names}"
    if failed:
        project, exc = failed[0]
        status += f". First failure: {project}: {exc}"
    return status


def bulk_delete_status(
    deleted: Sequence[str],
    blocked: Sequence[tuple[str, ProjectLifecycleBlockedError]],
    failed: Sequence[tuple[str, Exception]],
) -> str:
    if deleted and not blocked and not failed:
        return f"Deleted {len(deleted)} project(s)"

    parts: list[str] = []
    if deleted:
        parts.append(f"{len(deleted)} deleted")
    if blocked:
        parts.append(f"{len(blocked)} blocked")
    if failed:
        parts.append(f"{len(failed)} failed")
    if not parts:
        return "No marked projects deleted"

    status = "Delete marked projects: " + ", ".join(parts)
    if blocked:
        status += f". Blocked: {blocked[0][1]}"
    if failed:
        project, exc = failed[0]
        status += f". First failure: {project}: {exc}"
    return status
