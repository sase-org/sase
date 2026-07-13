"""Handler for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from sase.config.core import load_merged_config
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import (
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


def _print_human(inventory: RepoInventory) -> None:
    if not inventory.records:
        print("No repositories found.")
    else:
        print(f"{'NAME':<24} {'KIND':<8} {'PROJECT':<20} {'CLONED':<7} PATH")
        for record in inventory.records:
            print(
                f"{record.name:<24.24} "
                f"{record.kind:<8} "
                f"{record.project:<20.20} "
                f"{('yes' if record.exists else 'missing'):<7} "
                f"{record.path or '-'}"
            )

    for issue in inventory.issues:
        print(f"warning [{issue.project}]: {issue.message}", file=sys.stderr)


def _handle_list(args: argparse.Namespace) -> int:
    try:
        inventory = collect_repo_inventory(project=getattr(args, "project", None))
    except RepoInventoryProjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        print(json.dumps(inventory.to_json_dict(), indent=2, sort_keys=True))
    else:
        _print_human(inventory)
    return 0


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
