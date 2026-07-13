"""Handler for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Sequence
import json
import os
from pathlib import Path
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.config.core import load_merged_config
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import (
    RepoCloneRecord,
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    RepoRecord,
    collect_repo_inventory,
)
from sase.repo_open_log import append_repo_open_event, build_repo_open_event
from sase.workspace_provider.marker import find_marker_from_cwd
from sase.workspace_provider.store import WorkspaceStore


class _RepoOpenResolutionError(ValueError):
    """Raised when a repository or workspace context cannot be resolved."""


_KIND_STYLES = {
    "primary": "bold #00D7AF",
    "sidecar": "bold #AF87FF",
    "linked": "bold #87D7FF",
}


def _print_human(
    inventory: RepoInventory,
    *,
    workspace_num: int,
    project: str | None,
    console: Console | None = None,
) -> None:
    output = console or Console()
    grouped: dict[str, list[RepoRecord]] = defaultdict(list)
    for record in inventory.records:
        grouped[record.project].append(record)

    if project is not None:
        output.print(
            _repo_panel(
                grouped.get(project, list(inventory.records)),
                project=project,
                workspace_num=workspace_num,
            )
        )
    elif grouped:
        for project_name in sorted(grouped, key=str.casefold):
            output.print(
                _repo_panel(
                    grouped[project_name],
                    project=project_name,
                    workspace_num=workspace_num,
                )
            )
    else:
        output.print(Text("No repositories found.", style="dim"))

    if inventory.issues:
        warnings = Text()
        for index, issue in enumerate(inventory.issues):
            if index:
                warnings.append("\n")
            warnings.append(f"[{issue.project}] ", style="bold #FFD700")
            warnings.append(issue.message, style="dim")
        output.print(
            Panel(
                warnings,
                title="Inventory warnings",
                border_style="#FFD700",
                box=box.ROUNDED,
            )
        )


def _repo_panel(
    records: Sequence[RepoRecord],
    *,
    project: str,
    workspace_num: int,
) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("NAME", style="bold", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("CLONED", justify="center", no_wrap=True)
    table.add_column("WORKSPACES", justify="right", no_wrap=True)
    table.add_column("PATH", overflow="ellipsis", no_wrap=True, ratio=1)

    for record in records:
        clone = _clone_for_workspace(record, workspace_num)
        cloned_count = sum(item.exists for item in record.clones)
        total_count = len(record.clones)
        if not record.clones:
            cloned_count = int(record.exists)
            total_count = 1
        table.add_row(
            Text(record.name),
            Text(record.kind, style=_KIND_STYLES[record.kind]),
            Text(
                "✓" if clone.exists else "✗",
                style="green" if clone.exists else "#FFD700",
            ),
            f"{cloned_count}/{total_count}",
            Text(_compact_path(clone.path), style="dim" if clone.exists else "#FFD700"),
        )

    if not records:
        table.add_row(Text("No repositories found.", style="dim"), "", "", "", "")

    return Panel(
        table,
        title=f"Repos · {project} · workspace #{workspace_num}",
        title_align="left",
        border_style="#00D7AF",
        box=box.ROUNDED,
    )


def _compact_path(path: str, *, max_len: int = 72) -> str:
    value = path or "-"
    home = str(Path.home())
    if value == home or value.startswith(f"{home}/"):
        value = f"~{value[len(home) :]}"
    if len(value) <= max_len:
        return value
    return f"…{value[-(max_len - 1) :]}"


def _clone_for_workspace(record: RepoRecord, workspace_num: int) -> RepoCloneRecord:
    clone = record.clone_for_workspace(workspace_num)
    if clone is not None:
        return clone
    if workspace_num == 0:
        # Compatibility for callers constructing the pre-enrichment record
        # shape, including ACE fixtures and third-party consumers.
        return RepoCloneRecord(0, record.path, record.exists)
    raise _RepoOpenResolutionError(
        f"workspace #{workspace_num} is not registered for project '{record.project}'"
    )


def _handle_list(args: argparse.Namespace) -> int:
    from . import workspace_handler as workspace_commands

    all_projects = bool(getattr(args, "all_projects", False))
    requested_project = getattr(args, "project", None)
    if all_projects and requested_project:
        print("--all cannot be combined with --project", file=sys.stderr)
        return 2

    if all_projects:
        inventory = collect_repo_inventory(include_disabled=True)
        if getattr(args, "json", False):
            payload = _inventory_json_payload(inventory, workspace_num=0)
            payload["all_projects"] = True
            print(json.dumps(payload, indent=2, sort_keys=True))
            _print_inventory_issues_stderr(inventory)
        else:
            _print_human(inventory, workspace_num=0, project=None)
        return 0

    ctx = workspace_commands._resolve_project_context(requested_project)
    try:
        workspace_num = _resolve_list_workspace_num(
            ctx,
            getattr(args, "workspace", None),
        )
    except _RepoOpenResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        inventory = collect_repo_inventory(project=ctx.project_name)
    except RepoInventoryProjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        display_project = next(
            (record.project for record in inventory.records),
            ctx.project_name,
        )
        _validate_workspace_context(
            inventory.records,
            project=display_project,
            workspace_num=workspace_num,
        )
    except _RepoOpenResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        payload = _inventory_json_payload(inventory, workspace_num=workspace_num)
        payload["project"] = display_project
        payload["workspace_num"] = workspace_num
        print(json.dumps(payload, indent=2, sort_keys=True))
        _print_inventory_issues_stderr(inventory)
    else:
        _print_human(
            inventory,
            workspace_num=workspace_num,
            project=display_project,
        )
    return 0


def _resolve_list_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    cwd: Path | None = None,
) -> int:
    if requested_workspace is not None:
        workspace_num = int(requested_workspace)
        if workspace_num < 0:
            raise _RepoOpenResolutionError(
                f"workspace number must be >= 0, got {workspace_num}"
            )
        return workspace_num

    found = find_marker_from_cwd(str((cwd or Path.cwd()).resolve(strict=False)))
    if found is None:
        return 0
    _, marker = found
    marker_primary = Path(marker.primary_workspace_dir).resolve(strict=False)
    host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
    if marker_primary != host_primary:
        return 0
    return marker.workspace_num if marker.workspace_num >= 0 else 0


def _validate_workspace_context(
    records: Sequence[RepoRecord],
    *,
    project: str,
    workspace_num: int,
) -> None:
    if not records or workspace_num == 0:
        return
    registered = sorted(
        {clone.workspace_num for record in records for clone in record.clones}
    )
    if workspace_num in registered:
        return
    candidates = ", ".join(str(item) for item in registered) or "0"
    raise _RepoOpenResolutionError(
        f"workspace #{workspace_num} is not registered for project '{project}'. "
        f"Registered workspaces: {candidates}"
    )


def _inventory_json_payload(
    inventory: RepoInventory,
    *,
    workspace_num: int,
) -> dict[str, object]:
    return {
        "repos": [
            record.to_json_dict(workspace_num=workspace_num)
            for record in inventory.records
        ],
        "issues": [issue.to_json_dict() for issue in inventory.issues],
    }


def _print_inventory_issues_stderr(inventory: RepoInventory) -> None:
    for issue in inventory.issues:
        print(f"warning [{issue.project}]: {issue.message}", file=sys.stderr)


def _handle_open(args: argparse.Namespace) -> int:
    from . import workspace_handler as workspace_commands
    from .workspace_handler_list import (
        normalize_repo_open_reason,
        prepare_opened_checkout,
    )

    try:
        reason = normalize_repo_open_reason(getattr(args, "reason", None))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    host_ctx = workspace_commands._resolve_project_context(
        getattr(args, "project", None)
    )
    try:
        workspace_num = _resolve_open_workspace_num(
            host_ctx,
            getattr(args, "workspace", None),
        )
        inventory = collect_repo_inventory(project=host_ctx.project_name)
        repo = _resolve_repo_record(
            getattr(args, "repo", ""),
            host_ctx=host_ctx,
            inventory=inventory,
        )
    except (RepoInventoryProjectNotFoundError, _RepoOpenResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    target_ctx = _repo_target_context(host_ctx, repo)
    path = prepare_opened_checkout(
        target_ctx,
        workspace_num,
        reason=reason,
        resolve_checkout=workspace_commands._resolve_checkout_path,
    )
    if path is None:
        return 1

    _record_repo_open(
        host_ctx=host_ctx,
        repo=repo,
        workspace_num=workspace_num,
        path=path,
        reason=reason,
    )
    print(path)
    return 0


def _resolve_open_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    cwd: Path | None = None,
) -> int:
    if requested_workspace is not None:
        workspace_num = int(requested_workspace)
        if workspace_num < 0:
            raise _RepoOpenResolutionError(
                f"workspace number must be >= 0, got {workspace_num}"
            )
        return workspace_num

    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    found = find_marker_from_cwd(str(cwd_path))
    if found is not None:
        _, marker = found
        marker_primary = Path(marker.primary_workspace_dir).resolve(strict=False)
        host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
        if marker_primary != host_primary:
            raise _RepoOpenResolutionError(
                "Current directory belongs to a different project's workspace; "
                "pass -w/--workspace."
            )
        if marker.workspace_num < 0:
            raise _RepoOpenResolutionError(
                f"workspace marker has invalid number {marker.workspace_num}"
            )
        return marker.workspace_num

    host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
    if _is_relative_to(cwd_path, host_primary):
        return 0
    raise _RepoOpenResolutionError(
        "Unable to infer workspace from current directory; pass -w/--workspace."
    )


def _resolve_repo_record(
    name: str,
    *,
    host_ctx: ProjectContext,
    inventory: RepoInventory,
) -> RepoRecord:
    requested = name.strip()
    secondary_matches = [
        record
        for record in inventory.records
        if record.kind != "primary" and record.name == requested
    ]
    if len(secondary_matches) == 1:
        return secondary_matches[0]
    if len(secondary_matches) > 1:
        raise _ambiguous_repo_error(requested, secondary_matches)

    primary_matches = [
        record
        for record in inventory.records
        if record.kind == "primary"
        and requested in {record.name, host_ctx.project_name}
    ]
    if len(primary_matches) == 1:
        return primary_matches[0]
    if len(primary_matches) > 1:
        raise _ambiguous_repo_error(requested, primary_matches)

    valid_names = sorted(
        {
            record.name
            for record in inventory.records
            if record.project == host_ctx.project_name
        }
        | {host_ctx.project_name}
    )
    candidates = ", ".join(valid_names) or "none"
    raise _RepoOpenResolutionError(
        f"Unknown repo '{requested}' for project '{host_ctx.project_name}'. "
        f"Valid repos: {candidates}"
    )


def _ambiguous_repo_error(
    requested: str,
    matches: list[RepoRecord],
) -> _RepoOpenResolutionError:
    candidates = ", ".join(
        f"{record.kind} '{record.name}' ({record.path})" for record in matches
    )
    return _RepoOpenResolutionError(
        f"Repo name '{requested}' is ambiguous: {candidates}"
    )


def _repo_target_context(
    host_ctx: ProjectContext,
    repo: RepoRecord,
) -> ProjectContext:
    if repo.kind == "primary":
        return host_ctx
    return ProjectContext(
        project_name=repo.name,
        project_file=host_ctx.project_file,
        primary_workspace_dir=repo.path,
        store=WorkspaceStore(repo.path, config=load_merged_config()),
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=host_ctx.primary_workspace_dir,
    )


def _record_repo_open(
    *,
    host_ctx: ProjectContext,
    repo: RepoRecord,
    workspace_num: int,
    path: str,
    reason: str,
) -> None:
    try:
        event = build_repo_open_event(
            project=host_ctx.project_name,
            repo=repo.name,
            repo_kind=repo.kind,
            workspace_num=workspace_num,
            path=path,
            reason=reason,
            cwd=Path(os.getcwd()),
        )
        append_repo_open_event(event)
    except Exception as exc:
        print(f"Warning: unable to record repo open: {exc}", file=sys.stderr)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


_HANDLERS = {"list": _handle_list, "open": _handle_open}


def handle_repo_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase repo ...`` command."""

    subcommand = getattr(args, "repo_subcommand", None)
    handler = _HANDLERS.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print("Usage: sase repo {list,open}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(handler(args))


__all__ = ["handle_repo_command"]
