"""Pure rendering helpers for the Admin Center Projects sub-tab."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text

from sase.ace.tui.keymaps import (
    ProjectsPaneKeymaps,
    key_display_name,
    split_key_alternatives,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.current_project import CurrentProject
from sase.main.project_handler import ProjectLifecycleBlockedError

# Shared widths keep the fixed-width header and project rows aligned.
_MARK_WIDTH = 5
# Four columns so the header reads "CUR NAME" instead of the jammed
# "CURNAME" that a three-character "CUR" label would produce.
_CUR_WIDTH = 4
_NAME_WIDTH = 36
_VCS_WIDTH = 6
_STATE_WIDTH = 13
_CLAIMS_WIDTH = 8
_WORKSPACES_WIDTH = 5
_REPOS_WIDTH = 7
_WARN_WIDTH = 5


@dataclass(frozen=True)
class ProjectInventoryCounts:
    """Repo/workspace aggregates displayed alongside one project record."""

    repo_count: int = 0
    primary_repo_count: int = 0
    sidecar_repo_count: int = 0
    linked_repo_count: int = 0
    external_repo_count: int = 0
    workspace_count: int = 0
    claimed_workspace_count: int = 0
    issue_messages: tuple[str, ...] = ()


def _warning_count(
    record: ProjectRecordWire,
    counts: ProjectInventoryCounts,
) -> int:
    return (
        len(record.warnings) + len(record.parse_warnings) + len(counts.issue_messages)
    )


def _short_path(path: str | None, *, max_len: int = 72) -> str:
    if not path:
        return "-"
    text = str(Path(path).expanduser())
    if len(text) <= max_len:
        return text
    return "..." + text[-(max_len - 3) :]


def _state_style(state: str) -> str:
    if state == "enabled":
        return "bold #00D7AF"
    if state == "disabled":
        return "bold #FFD700"
    return "bold"


def _state_badge(state: str) -> str:
    return f"{'●' if state == 'enabled' else '○'} {state}"


def _vcs_style(vcs_kind: str | None) -> str:
    if vcs_kind == "gh":
        return "bold #87D7FF"
    if vcs_kind == "git":
        return "bold #00D7AF"
    return "dim"


def _launch_label(record: ProjectRecordWire) -> str:
    return "yes" if record.launchable and record.state == "enabled" else "no"


def _project_label(record: ProjectRecordWire) -> str:
    display = effective_project_name(record)
    if display == record.project_name:
        return display
    return f"{display} ({record.project_name})"


def _name_style(*, is_current: bool, accent: str) -> str:
    if is_current and accent:
        return f"bold {accent}"
    return "bold"


def _is_current_project(
    record: ProjectRecordWire,
    *,
    current_project: CurrentProject | None,
    current_project_key: str | None,
) -> bool:
    resolved_key = (
        current_project.project_key
        if current_project is not None
        else current_project_key
    )
    return resolved_key is not None and record.project_name == resolved_key


def _current_project_via_text(current_project: CurrentProject) -> str:
    ref = f"#{current_project.workflow_type}:{current_project.origin_ref}"
    if current_project.origin == "patch":
        return f"via Patch {current_project.origin_ref} ({ref})"
    return f"via {ref}"


def _current_project_detail_reason(record: ProjectRecordWire) -> str:
    display = effective_project_name(record)
    if record.state != "enabled":
        return f"enable {display} first (a), then press c"
    if not record.launchable:
        return f"{display} has no launchable ProjectSpec"
    return f"press c to make {display} current"


def _append_current_project_summary(
    text: Text,
    *,
    current_project_key: str | None,
    current_project_name: str | None,
    current_project_accent: str,
    current_project_loaded: bool,
) -> None:
    text.append("  ·  current:", style="dim")
    if not current_project_loaded:
        text.append("…", style="dim")
        return
    name = current_project_name or current_project_key
    if not name:
        text.append("none", style="dim")
        return
    plus_style = f"dim {current_project_accent}" if current_project_accent else "dim"
    name_style = f"bold {current_project_accent}" if current_project_accent else "bold"
    text.append("+", style=plus_style)
    text.append(name, style=name_style)


def column_header_text(
    *,
    current_project_key: str | None = None,
    current_project_accent: str = "",
) -> Text:
    """Return the fixed-width project table header."""

    del current_project_key, current_project_accent
    text = Text(style="bold dim")
    text.append(f"{'MARK':<{_MARK_WIDTH}}")
    text.append(f"{'CUR':<{_CUR_WIDTH}}")
    text.append(f"{'NAME':<{_NAME_WIDTH}}")
    text.append(f"{'VCS':<{_VCS_WIDTH}}")
    text.append(f"{'STATE':<{_STATE_WIDTH}}")
    text.append(f"{'CLAIMS':<{_CLAIMS_WIDTH}}")
    text.append(f"{'WS':<{_WORKSPACES_WIDTH}}")
    text.append(f"{'REPOS':<{_REPOS_WIDTH}}")
    text.append(f"{'WARN':<{_WARN_WIDTH}}")
    return text


def record_label(
    record: ProjectRecordWire,
    marked_projects: set[str],
    counts: ProjectInventoryCounts | None = None,
    *,
    current_project_key: str | None = None,
    current_project_accent: str = "",
) -> Text:
    """Render one project row using the new project/repo/workspace taxonomy."""

    resolved_counts = counts or ProjectInventoryCounts()
    text = Text()
    if record.project_name in marked_projects:
        text.append(f"{'[✓]':<{_MARK_WIDTH}}", style="bold #00D700")
    else:
        text.append(" " * _MARK_WIDTH)
    is_current = _is_current_project(
        record,
        current_project=None,
        current_project_key=current_project_key,
    )
    if is_current:
        plus_style = (
            f"bold {current_project_accent}" if current_project_accent else "bold"
        )
        text.append(f"{'+':<{_CUR_WIDTH}}", style=plus_style)
    else:
        text.append(" " * _CUR_WIDTH)
    label = _project_label(record)
    text.append(
        f"{label:<{_NAME_WIDTH}.{_NAME_WIDTH}}",
        style=_name_style(is_current=is_current, accent=current_project_accent),
    )
    vcs_kind = record.vcs_kind or "-"
    text.append(
        f"{vcs_kind:<{_VCS_WIDTH}.{_VCS_WIDTH}}",
        style=_vcs_style(record.vcs_kind),
    )
    badge = _state_badge(record.state)
    text.append(
        f"{badge:<{_STATE_WIDTH}.{_STATE_WIDTH}}",
        style=_state_style(record.state),
    )
    text.append(f"{record.active_claim_count:<{_CLAIMS_WIDTH}}")
    text.append(f"{resolved_counts.workspace_count:<{_WORKSPACES_WIDTH}}")
    text.append(f"{resolved_counts.repo_count:<{_REPOS_WIDTH}}")
    warnings = _warning_count(record, resolved_counts)
    if warnings:
        text.append(f"{warnings:<{_WARN_WIDTH}}", style="bold red")
    else:
        text.append(f"{'-':<{_WARN_WIDTH}}", style="dim")
    return text


def summary_text(
    records: Sequence[ProjectRecordWire],
    text_filter: str,
    status_message: str,
    marked_projects: set[str],
    *,
    inventory_loading: bool = False,
    inventory_error: str = "",
    current_project_key: str | None = None,
    current_project_accent: str = "",
    current_project_name: str | None = None,
    current_project_loaded: bool = False,
) -> Text:
    """Render project lifecycle counts and transient load/action status."""

    enabled = sum(record.state == "enabled" for record in records)
    disabled = sum(record.state == "disabled" for record in records)
    text = Text()
    text.append("enabled:", style="dim")
    text.append(str(enabled), style="bold #00D7AF")
    text.append("  ·  disabled:", style="dim")
    text.append(str(disabled), style="bold #FFD700" if disabled else "dim")
    text.append("  ·  marked:", style="dim")
    mark_count = len(marked_projects)
    text.append(str(mark_count), style="bold #00D700" if mark_count else "dim")
    _append_current_project_summary(
        text,
        current_project_key=current_project_key,
        current_project_name=current_project_name,
        current_project_accent=current_project_accent,
        current_project_loaded=current_project_loaded,
    )
    if text_filter:
        text.append(f"  ·  search:{text_filter}", style="dim")
    if inventory_loading:
        text.append("  ·  refreshing counts…", style="#87D7FF")
    if inventory_error:
        text.append(f"  ·  counts: {inventory_error}", style="bold red")
    if status_message:
        text.append(f"  ·  {status_message}", style="#87D7FF")
    return text


def _primary_key_display(key: str) -> str:
    """Return the display form of a configured key's first alternative."""

    return key_display_name(split_key_alternatives(key)[0])


def hints_text(
    marked_projects: set[str],
    keymaps: ProjectsPaneKeymaps,
    *,
    jump_active: bool = False,
    jump_back: bool = False,
) -> str:
    """Return the one-line Projects sub-tab key hints."""

    jump_key = key_display_name(keymaps.jump_to_entry)
    if jump_active:
        return f"JUMP {jump_key} {'back' if jump_back else 'first'}  <esc> cancel"
    move_keys = "/".join(
        _primary_key_display(key) for key in (keymaps.next_option, keymaps.prev_option)
    )
    subtab_keys = " / ".join(
        key_display_name(key)
        for key in (keymaps.cycle_subtab_reverse, keymaps.cycle_subtab)
    )
    # This line already overflows 120 columns, so the leading segments are
    # kept short enough that adding the jump key displaces nothing that used
    # to be visible.
    base = (
        f"{move_keys} move  {jump_key} jump  "
        f"{key_display_name(keymaps.focus_filter)} filter  "
        f"{subtab_keys} sub-tab  "
        f"{key_display_name(keymaps.default_project_action)} enable  "
        f"{key_display_name(keymaps.show_project_repos)} repos  "
        f"{key_display_name(keymaps.show_project_workspaces)} workspaces  "
        f"{key_display_name(keymaps.toggle_project_mark)} mark  "
        f"{key_display_name(keymaps.clear_project_marks)} unmark all  "
        f"{key_display_name(keymaps.edit_project_spec)} edit  "
        f"{key_display_name(keymaps.edit_project_aliases)} aliases  "
        f"{key_display_name(keymaps.enable_project)} enable  "
        f"{key_display_name(keymaps.disable_project)} disable  "
        f"{key_display_name(keymaps.delete_project)} delete  "
        f"{key_display_name(keymaps.force_current_state_change)} force after block  "
        f"{key_display_name(keymaps.reload)} reload  "
        f"{key_display_name(keymaps.set_current_project)} current"
    )
    mark_count = len(marked_projects)
    if mark_count:
        target_keys = "/".join(
            key_display_name(key)
            for key in (
                keymaps.enable_project,
                keymaps.disable_project,
                keymaps.delete_project,
            )
        )
        base = f"{base}  marked:{mark_count} ({target_keys} target marked set)"
    return f"{base}  Tab/Shift+Tab switch tab   q close"


def detail_text(
    record: ProjectRecordWire | None,
    marked_projects: set[str],
    counts: ProjectInventoryCounts | None = None,
    *,
    current_project: CurrentProject | None = None,
    current_project_key: str | None = None,
    current_project_accent: str = "",
) -> Text:
    """Render the selected project's details and inventory aggregates."""

    text = Text()
    if record is None:
        text.append("No project selected", style="dim")
        return text

    resolved_counts = counts or ProjectInventoryCounts()
    display = effective_project_name(record)
    is_current = _is_current_project(
        record,
        current_project=current_project,
        current_project_key=current_project_key,
    )
    text.append(display, style="bold")
    if display != record.project_name:
        text.append(f" ({record.project_name})", style="dim")
    text.append("   ")
    text.append(_state_badge(record.state), style=_state_style(record.state))
    text.append("    VCS: ", style="dim")
    text.append(record.vcs_kind or "-", style=_vcs_style(record.vcs_kind))
    if is_current:
        badge_style = (
            f"bold {current_project_accent}" if current_project_accent else "bold"
        )
        text.append("    +CURRENT", style=badge_style)
    text.append("\nProject file:  ", style="dim")
    text.append(str(record.project_file))
    text.append("\nPrimary repo:  ", style="dim")
    text.append(_short_path(record.workspace_dir))
    text.append("\nRepos: ", style="dim")
    text.append(str(resolved_counts.repo_count))
    text.append(
        " ("
        f"{resolved_counts.primary_repo_count} primary · "
        f"{resolved_counts.sidecar_repo_count} sidecar · "
        f"{resolved_counts.linked_repo_count} linked"
    )
    if resolved_counts.external_repo_count:
        text.append(f" · {resolved_counts.external_repo_count} external")
    text.append(")")
    text.append("    Workspaces: ", style="dim")
    text.append(
        f"{resolved_counts.workspace_count} "
        f"({resolved_counts.claimed_workspace_count} claimed)"
    )
    text.append("\nAliases: ", style="dim")
    text.append(", ".join(record.aliases) if record.aliases else "-")
    text.append("    Display name: ", style="dim")
    text.append(display)
    text.append("    Launchable: ", style="dim")
    text.append(_launch_label(record))
    if is_current:
        yes_line = "Current project: yes"
        if current_project is not None:
            yes_line = f"{yes_line}  ·  {_current_project_via_text(current_project)}"
        text.append(f"\n{yes_line}", style="#87D7FF")
    else:
        text.append(
            f"\nCurrent project: no   ·  {_current_project_detail_reason(record)}",
            style="#87D7FF",
        )
    if marked_projects:
        row_state = "marked" if record.project_name in marked_projects else "not marked"
        text.append(
            "\nMarked set: "
            f"{len(marked_projects)} project(s); "
            "a/d/Ctrl+D target marked projects; "
            f"this row is {row_state}.",
            style="#87D7FF",
        )
    warnings = [
        *record.warnings,
        *record.parse_warnings,
        *resolved_counts.issue_messages,
    ]
    if warnings:
        text.append("\nWarnings:", style="bold red")
        for warning in warnings:
            text.append(f"\n  - {warning}", style="red")
    if record.state == "disabled":
        text.append(
            f"\nHint: press a or Enter to enable {display}.",
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


__all__ = [
    "ProjectInventoryCounts",
    "bulk_delete_message",
    "bulk_delete_status",
    "column_header_text",
    "detail_text",
    "force_state_change_message",
    "hints_text",
    "record_label",
    "state_change_status",
    "summary_text",
    "truncated_project_lines",
]
