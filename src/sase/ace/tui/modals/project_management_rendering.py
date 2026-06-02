"""Rendering and status helpers for the project management modal."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from rich.text import Text

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.project_handler import ProjectLifecycleBlockedError


def warning_count(record: ProjectRecordWire) -> int:
    return len(record.warnings) + len(record.parse_warnings)


def short_path(path: str | None, *, max_len: int = 46) -> str:
    if not path:
        return "-"
    text = str(Path(path).expanduser())
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3) :]


def state_style(state: str) -> str:
    if state == "active":
        return "bold #00D7AF"
    if state == "archived":
        return "bold #FFD700"
    if state == "closed":
        return "bold #FF8C00"
    return "bold"


def record_label(record: ProjectRecordWire, marked_projects: set[str]) -> Text:
    text = Text()
    if record.project_name in marked_projects:
        text.append("[✓] ", style="bold #00D700")
    else:
        text.append("    ", style="dim")
    text.append(f"{record.project_name:<24.24}", style="bold")
    text.append("  ")
    text.append(f"{record.state:<8}", style=state_style(record.state))
    if not record.state_explicit:
        text.append(" default", style="dim")
    else:
        text.append("        ")
    text.append(f"  claims:{record.active_claim_count:<2}")
    launch = "yes" if record.launchable and record.state == "active" else "no"
    text.append(f"  launch:{launch:<3}")
    if warning_count(record):
        text.append(f"  warnings:{warning_count(record)}", style="bold red")
    text.append("  ")
    text.append(short_path(record.workspace_dir), style="dim")
    return text


def summary_text(
    records: Sequence[ProjectRecordWire],
    state_filter: str,
    text_filter: str,
    status_message: str,
    marked_projects: set[str],
) -> Text:
    counts: dict[str, int] = {"active": 0, "archived": 0, "closed": 0}
    for record in records:
        if record.state in counts:
            counts[record.state] += 1
    text = Text()
    text.append("Filter: ", style="dim")
    text.append(state_filter, style="bold")
    text.append(
        f"  all:{len(records)} active:{counts['active']} "
        f"archived:{counts['archived']} closed:{counts['closed']}",
        style="dim",
    )
    mark_count = len(marked_projects)
    text.append("  marked:", style="dim")
    text.append(
        str(mark_count),
        style="bold #00D700" if mark_count else "dim",
    )
    if text_filter:
        text.append(f"  search:{text_filter}", style="dim")
    if status_message:
        text.append(f"  {status_message}", style="#87D7FF")
    return text


def footer_text(marked_projects: set[str]) -> str:
    base = (
        "j/k navigate  / filter  Tab/Shift+Tab state  Enter highlighted  "
        "m mark  u unmark all  e edit  a activate  r archive  c close  "
        "Ctrl+D delete  F force after block  R reload  q close"
    )
    mark_count = len(marked_projects)
    if not mark_count:
        return base
    return f"{base}  marked:{mark_count} (a/r/c/Ctrl+D target marked set)"


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
    text.append(record.project_name, style="bold")
    text.append("  ")
    text.append(record.state, style=state_style(record.state))
    text.append(f" ({source})")
    text.append(f"\nProject file: {record.project_file}", style="dim")
    text.append(f"\nWorkspace: {short_path(record.workspace_dir, max_len=72)}")
    text.append(f"\nActive claims: {record.active_claim_count}    Launchable: {launch}")
    if marked_projects:
        row_state = "marked" if record.project_name in marked_projects else "not marked"
        text.append(
            "\nMarked set: "
            f"{len(marked_projects)} project(s); "
            "a/r/c/Ctrl+D target marked projects; "
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
            f"\nHint: press a or Enter to reactivate {record.project_name}.",
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
        lines.append(f"  - {record.project_name}: {project_dir_for(record)}")
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
            return f"{updated.project_name} -> {updated.state}"
        if skipped:
            return f"{records[0].project_name} is already {state}"
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
