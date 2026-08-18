"""Pure rendering helpers for repository and workspace inventory sub-tabs."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rich.text import Text

from sase.ace.tui.keymaps import (
    ProjectsPaneKeymaps,
    key_display_name,
    split_key_alternatives,
)
from sase.core.time import format_local
from sase.repo_inventory import RepoRecord
from sase.workspace_provider.inventory import WorkspaceInventoryRecord

_REPO_NAME_WIDTH = 25
_REPO_KIND_WIDTH = 11
_REPO_PROJECT_WIDTH = 19
_REPO_CLONED_WIDTH = 10

_WORKSPACE_NUM_WIDTH = 5
_WORKSPACE_PROJECT_WIDTH = 17
_WORKSPACE_CLAIM_WIDTH = 29
_WORKSPACE_ROLE_WIDTH = 11
_WORKSPACE_PIN_WIDTH = 6
_WORKSPACE_LAST_USED_WIDTH = 13
_WORKSPACE_STALE_WIDTH = 8

_REPO_KIND_STYLES = {
    "primary": "bold #00D7AF",
    "sidecar": "bold #AF87FF",
    "linked": "bold #87D7FF",
    "external": "bold #FFAF00",
}


def _compact_path(path: str, *, max_len: int = 54) -> str:
    """Return a home-relative path, tail-truncated to *max_len*."""

    value = path or "-"
    try:
        home = str(Path.home())
    except (OSError, RuntimeError):
        home = ""
    if home and (value == home or value.startswith(f"{home}/")):
        value = f"~{value[len(home) :]}"
    if len(value) <= max_len:
        return value
    return f"…{value[-(max_len - 1) :]}"


def _project_scope_label(project: str | None) -> str:
    return project or "all"


def repo_column_header_text() -> Text:
    """Return the fixed-width repository table header."""

    text = Text(style="bold dim")
    text.append(f"{'NAME':<{_REPO_NAME_WIDTH}}")
    text.append(f"{'KIND':<{_REPO_KIND_WIDTH}}")
    text.append(f"{'PROJECT':<{_REPO_PROJECT_WIDTH}}")
    text.append(f"{'CLONED':<{_REPO_CLONED_WIDTH}}")
    text.append("PATH")
    return text


def repo_record_label(record: RepoRecord) -> Text:
    """Render one repository inventory row."""

    text = Text()
    text.append(
        f"{record.name:<{_REPO_NAME_WIDTH}.{_REPO_NAME_WIDTH}}",
        style="bold",
    )
    kind_style = _REPO_KIND_STYLES[record.kind]
    text.append(
        f"{record.kind:<{_REPO_KIND_WIDTH}.{_REPO_KIND_WIDTH}}",
        style=kind_style,
    )
    text.append(
        f"{record.project:<{_REPO_PROJECT_WIDTH}.{_REPO_PROJECT_WIDTH}}",
    )
    cloned = "yes" if record.exists else "missing"
    text.append(
        f"{cloned:<{_REPO_CLONED_WIDTH}.{_REPO_CLONED_WIDTH}}",
        style="bold red" if not record.exists else "#00D7AF",
    )
    text.append(
        _compact_path(record.path),
        style="bold red" if not record.exists else "dim",
    )
    return text


def repo_summary_text(
    records: Sequence[RepoRecord],
    *,
    project: str | None,
    text_filter: str,
    issue_count: int,
    loading: bool,
    error: str,
) -> Text:
    """Render repository totals and active filters."""

    text = Text()
    text.append("repos:", style="dim")
    text.append(str(len(records)), style="bold")
    kinds = ["primary", "sidecar", "linked"]
    if any(record.kind == "external" for record in records):
        kinds.append("external")
    for kind in kinds:
        count = sum(record.kind == kind for record in records)
        text.append(f"  ·  {kind}:", style="dim")
        text.append(str(count), style=_REPO_KIND_STYLES[kind])
    text.append("  ·  project:", style="dim")
    text.append(_project_scope_label(project), style="bold #FFAF5F")
    if text_filter:
        text.append(f"  ·  search:{text_filter}", style="dim")
    if issue_count:
        text.append(f"  ·  warnings:{issue_count}", style="bold red")
    if loading:
        text.append("  ·  refreshing…", style="#87D7FF")
    if error:
        text.append(f"  ·  {error}", style="bold red")
    return text


def repo_detail_text(
    record: RepoRecord | None,
    *,
    issues: Sequence[str] = (),
) -> Text:
    """Render full metadata for the selected repository."""

    text = Text()
    if record is None:
        text.append("No repository selected", style="dim")
        return text

    text.append(record.name, style="bold")
    text.append("   ")
    text.append(record.kind, style=_REPO_KIND_STYLES[record.kind])
    text.append("    Project: ", style="dim")
    text.append(record.project)
    text.append("\nCheckout:  ", style="dim")
    text.append(record.path or "-")
    text.append("    Status: ", style="dim")
    text.append(
        "cloned" if record.exists else "missing",
        style="#00D7AF" if record.exists else "bold red",
    )
    text.append("\nSource:    ", style="dim")
    text.append(record.source)
    text.append("    Auto-clone: ", style="dim")
    text.append("yes" if record.auto_clone else "no")
    text.append("    Auto-sync: ", style="dim")
    text.append("yes" if record.auto_sync else "no")
    text.append("\nDescription: ", style="dim")
    text.append(record.description or "-")
    text.append("\nEnvironment: ", style="dim")
    if record.env_name:
        text.append(f"SASE_LINKED_REPO_{record.env_name}_DIR")
    else:
        text.append("-")
    if record.sdd_storage:
        text.append("    SDD storage: ", style="dim")
        text.append(record.sdd_storage)
    warnings = list(issues)
    if not record.exists:
        warnings.insert(0, "Checkout is missing on disk")
    if warnings:
        text.append("\nWarnings:", style="bold red")
        for warning in warnings:
            text.append(f"\n  - {warning}", style="red")
    return text


def repo_hints_text(
    keymaps: ProjectsPaneKeymaps,
    *,
    project_filtered: bool,
    jump_active: bool = False,
    jump_back: bool = False,
) -> str:
    """Return one-line key hints for the repository inventory."""

    return _inventory_hints_text(
        keymaps,
        project_filtered=project_filtered,
        jump_active=jump_active,
        jump_back=jump_back,
    )


def workspace_column_header_text() -> Text:
    """Return the fixed-width workspace table header."""

    text = Text(style="bold dim")
    text.append(f"{'#':<{_WORKSPACE_NUM_WIDTH}}")
    text.append(f"{'PROJECT':<{_WORKSPACE_PROJECT_WIDTH}}")
    text.append(f"{'CLAIMED BY':<{_WORKSPACE_CLAIM_WIDTH}}")
    text.append(f"{'ROLE':<{_WORKSPACE_ROLE_WIDTH}}")
    text.append(f"{'PIN':<{_WORKSPACE_PIN_WIDTH}}")
    text.append(f"{'LAST USED':<{_WORKSPACE_LAST_USED_WIDTH}}")
    text.append(f"{'STALE':<{_WORKSPACE_STALE_WIDTH}}")
    text.append("PATH")
    return text


def _relative_workspace_time(timestamp: float, *, now: float) -> str:
    """Format a registry timestamp as a compact stable relative label."""

    elapsed = max(0, int(now - timestamp))
    if elapsed < 30:
        return "now"
    if elapsed < 3600:
        return f"{elapsed // 60}m ago"
    if elapsed < 86400:
        return f"{elapsed // 3600}h ago"
    return f"{elapsed // 86400}d ago"


def _absolute_workspace_time(timestamp: float) -> str:
    return format_local(timestamp, "%Y-%m-%d %H:%M", default="-")


def _claim_label(record: WorkspaceInventoryRecord) -> tuple[str, str]:
    if not record.claimed:
        return "-", "dim"
    label = record.claim_agent or "unknown"
    if record.claim_pid_alive is False:
        return f"{label} ⚠ dead", "bold red"
    return label, "#87D7FF"


def workspace_record_label(
    record: WorkspaceInventoryRecord,
    *,
    now: float,
) -> Text:
    """Render one workspace inventory row."""

    text = Text()
    text.append(f"{record.workspace_num:<{_WORKSPACE_NUM_WIDTH}}", style="bold")
    text.append(
        f"{record.project:<{_WORKSPACE_PROJECT_WIDTH}.{_WORKSPACE_PROJECT_WIDTH}}"
    )
    claim, claim_style = _claim_label(record)
    text.append(
        f"{claim:<{_WORKSPACE_CLAIM_WIDTH}.{_WORKSPACE_CLAIM_WIDTH}}",
        style=claim_style,
    )
    text.append(f"{record.role:<{_WORKSPACE_ROLE_WIDTH}.{_WORKSPACE_ROLE_WIDTH}}")
    text.append(
        f"{'●' if record.pinned else '-':<{_WORKSPACE_PIN_WIDTH}}",
        style="bold #AF87FF" if record.pinned else "dim",
    )
    last_used = _relative_workspace_time(record.last_used_at, now=now)
    text.append(f"{last_used:<{_WORKSPACE_LAST_USED_WIDTH}}")
    text.append(
        f"{'●' if record.stale else '-':<{_WORKSPACE_STALE_WIDTH}}",
        style="bold #FFD700" if record.stale else "dim",
    )
    path = _compact_path(record.checkout_dir, max_len=48)
    if not record.exists:
        path = f"missing {path}"
    text.append(path, style="bold red" if not record.exists else "dim")
    return text


def workspace_summary_text(
    records: Sequence[WorkspaceInventoryRecord],
    *,
    project: str | None,
    text_filter: str,
    issue_count: int,
    loading: bool,
    error: str,
) -> Text:
    """Render workspace totals and active filters."""

    text = Text()
    text.append("workspaces:", style="dim")
    text.append(str(len(records)), style="bold")
    for label, count, style in (
        ("claimed", sum(record.claimed for record in records), "#87D7FF"),
        ("pinned", sum(record.pinned for record in records), "#AF87FF"),
        ("stale", sum(record.stale for record in records), "#FFD700"),
    ):
        text.append(f"  ·  {label}:", style="dim")
        text.append(str(count), style=f"bold {style}")
    text.append("  ·  project:", style="dim")
    text.append(_project_scope_label(project), style="bold #FFAF5F")
    if text_filter:
        text.append(f"  ·  search:{text_filter}", style="dim")
    if issue_count:
        text.append(f"  ·  warnings:{issue_count}", style="bold red")
    if loading:
        text.append("  ·  refreshing…", style="#87D7FF")
    if error:
        text.append(f"  ·  {error}", style="bold red")
    return text


def workspace_detail_text(
    record: WorkspaceInventoryRecord | None,
    *,
    now: float,
    issues: Sequence[str] = (),
) -> Text:
    """Render full metadata for the selected workspace."""

    text = Text()
    if record is None:
        text.append("No workspace selected", style="dim")
        return text

    text.append(f"{record.project} #{record.workspace_num}", style="bold")
    text.append("   ")
    text.append(record.role, style="#00D7AF")
    text.append(f" · {record.materialization} · generation {record.generation}")
    text.append("\nClaim: ", style="dim")
    if record.claimed:
        text.append(record.claim_agent or "unknown", style="bold")
        text.append(f"  pid {record.claim_pid or '-'} ")
        if record.claim_pid_alive is False:
            text.append("(dead)", style="bold red")
        elif record.claim_pid_alive is True:
            text.append("(alive)", style="#00D7AF")
        else:
            text.append("(unknown)", style="dim")
        text.append(f"  CL {record.claim_cl_name or '-'}")
        text.append(f"  since {record.claim_timestamp or '-'}")
    else:
        text.append("-", style="dim")
    text.append("\nCreated: ", style="dim")
    text.append(_absolute_workspace_time(record.created_at))
    text.append("    Last used: ", style="dim")
    text.append(
        f"{_absolute_workspace_time(record.last_used_at)} "
        f"({_relative_workspace_time(record.last_used_at, now=now)})"
    )
    text.append("    Stale: ", style="dim")
    text.append(
        f"{'yes' if record.stale else 'no'} (TTL {record.cleanup_ttl_days}d)",
        style="bold #FFD700" if record.stale else "#00D7AF",
    )
    text.append("\nCheckout: ", style="dim")
    text.append(record.checkout_dir)
    text.append("\nRegistry: ", style="dim")
    text.append(record.registry_path)
    warnings = list(issues)
    if not record.exists:
        warnings.insert(
            0,
            "Checkout is missing on disk; run `sase workspace repair`",
        )
    if record.claimed and record.claim_pid_alive is False:
        warnings.insert(0, f"Claim PID {record.claim_pid} is not running")
    if warnings:
        text.append("\nWarnings:", style="bold red")
        for warning in warnings:
            text.append(f"\n  - {warning}", style="red")
    return text


def workspace_hints_text(
    keymaps: ProjectsPaneKeymaps,
    *,
    project_filtered: bool,
    jump_active: bool = False,
    jump_back: bool = False,
) -> str:
    """Return one-line key hints for the workspace inventory."""

    return _inventory_hints_text(
        keymaps,
        project_filtered=project_filtered,
        jump_active=jump_active,
        jump_back=jump_back,
    )


def _inventory_hints_text(
    keymaps: ProjectsPaneKeymaps,
    *,
    project_filtered: bool,
    jump_active: bool,
    jump_back: bool,
) -> str:
    """Return the shared one-line hints both inventory sub-tabs render."""

    jump_key = key_display_name(keymaps.jump_to_entry)
    if jump_active:
        return f"JUMP {jump_key} {'back' if jump_back else 'first'}  <esc> cancel"
    move_keys = "/".join(
        key_display_name(split_key_alternatives(key)[0])
        for key in (keymaps.next_option, keymaps.prev_option)
    )
    subtab_keys = " / ".join(
        key_display_name(key)
        for key in (keymaps.cycle_subtab_reverse, keymaps.cycle_subtab)
    )
    escape = (
        f"  {key_display_name(keymaps.clear_project_filter)} clear project"
        if project_filtered
        else ""
    )
    return (
        f"{move_keys} navigate  {jump_key} jump  "
        f"{key_display_name(keymaps.focus_filter)} filter  "
        f"{key_display_name(keymaps.pick_project)} pick project  "
        f"{subtab_keys} sub-tab  "
        f"{key_display_name(keymaps.reload)} reload"
        f"{escape}  Tab/Shift+Tab switch tab   q close"
    )


__all__ = [
    "repo_column_header_text",
    "repo_detail_text",
    "repo_hints_text",
    "repo_record_label",
    "repo_summary_text",
    "workspace_column_header_text",
    "workspace_detail_text",
    "workspace_hints_text",
    "workspace_record_label",
    "workspace_summary_text",
]
