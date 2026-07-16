"""Facade and dispatcher for the ``sase repo`` CLI command."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.config.core import load_merged_config
from sase.repo_inventory import (
    RepoInventory,
    RepoKind,
    RepoRecord,
    collect_repo_inventory,
)
from sase.workspace_provider.marker import find_marker_from_cwd

from .repo_handler_common import (
    RepoOpenResolutionError,
    ambiguous_repo_error,
    clone_for_workspace,
    is_relative_to,
    match_repo_record,
    resolve_list_workspace_num,
    validate_workspace_context,
)
from .repo_handler_list import (
    compact_path,
    handle_list_command,
    inventory_json_payload,
    print_human,
    print_inventory_issues_stderr,
    repo_panel,
)
from .repo_handler_open import (
    handle_open_command,
    record_repo_open,
    repo_target_context,
    resolve_open_workspace_num,
)
from .repo_handler_path import (
    handle_path_command,
    match_repo_path_record,
    resolve_legacy_sdd_repo_path,
    sidecar_role_disabled,
)
from .workspace_handler_context import ProjectContext


# Compatibility aliases for callers that imported the old module's helpers.
_RepoOpenResolutionError = RepoOpenResolutionError
_ambiguous_repo_error = ambiguous_repo_error
_clone_for_workspace = clone_for_workspace
_compact_path = compact_path
_inventory_json_payload = inventory_json_payload
_is_relative_to = is_relative_to
_match_repo_path_record = match_repo_path_record
_match_repo_record = match_repo_record
_print_human = print_human
_print_inventory_issues_stderr = print_inventory_issues_stderr
_repo_panel = repo_panel
_resolve_legacy_sdd_repo_path = resolve_legacy_sdd_repo_path
_validate_workspace_context = validate_workspace_context


def _resolve_list_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    cwd: Path | None = None,
) -> int:
    return resolve_list_workspace_num(
        host_ctx,
        requested_workspace,
        find_marker=find_marker_from_cwd,
        cwd=cwd,
    )


def _resolve_open_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    cwd: Path | None = None,
) -> int:
    return resolve_open_workspace_num(
        host_ctx,
        requested_workspace,
        find_marker=find_marker_from_cwd,
        cwd=cwd,
    )


def _repo_target_context(
    host_ctx: ProjectContext,
    repo: RepoRecord,
) -> ProjectContext:
    return repo_target_context(host_ctx, repo, load_config=load_merged_config)


def _record_repo_open(
    *,
    host_ctx: ProjectContext,
    repo_name: str,
    repo_kind: RepoKind,
    workspace_num: int,
    path: str,
    reason: str,
) -> None:
    record_repo_open(
        host_ctx=host_ctx,
        repo_name=repo_name,
        repo_kind=repo_kind,
        workspace_num=workspace_num,
        path=path,
        reason=reason,
    )


def _sidecar_role_disabled(
    role: str,
    *,
    primary_workspace_dir: str,
) -> bool:
    return sidecar_role_disabled(
        role,
        primary_workspace_dir=primary_workspace_dir,
    )


def _handle_list(args: argparse.Namespace) -> int:
    from . import workspace_handler as workspace_commands

    return handle_list_command(
        args,
        collect_inventory=collect_repo_inventory,
        resolve_project_context=workspace_commands._resolve_project_context,
        resolve_workspace_num=_resolve_list_workspace_num,
        validate_workspace=_validate_workspace_context,
    )


def _handle_open(args: argparse.Namespace) -> int:
    from . import workspace_handler as workspace_commands

    return handle_open_command(
        args,
        collect_inventory=collect_repo_inventory,
        resolve_project_context=workspace_commands._resolve_project_context,
        resolve_checkout=workspace_commands._resolve_checkout_path,
        resolve_workspace_num=_resolve_open_workspace_num,
        match_repo=_match_repo_record,
        target_context=_repo_target_context,
        record_repo_open=_record_repo_open,
    )


def _handle_log(args: argparse.Namespace) -> int:
    from sase.project_display_names import project_display_name_for
    from sase.repo_open_cli_log import handle_repo_log_command

    from . import workspace_handler as workspace_commands

    host_ctx = workspace_commands._resolve_project_context(
        getattr(args, "project", None)
    )
    return handle_repo_log_command(
        args,
        project_name=project_display_name_for(host_ctx.project_name),
        log_project_name=host_ctx.project_name,
    )


def _handle_path(args: argparse.Namespace) -> int:
    from . import workspace_handler as workspace_commands

    return handle_path_command(
        args,
        collect_inventory=collect_repo_inventory,
        resolve_project_context=workspace_commands._resolve_project_context,
        resolve_workspace_num=_resolve_list_workspace_num,
        validate_workspace=_validate_workspace_context,
        sidecar_role_disabled=_sidecar_role_disabled,
    )


def _handle_init(args: argparse.Namespace) -> int:
    from .repo_init_handler import run_repo_init

    return run_repo_init(args)


_HANDLERS = {
    "init": _handle_init,
    "list": _handle_list,
    "log": _handle_log,
    "open": _handle_open,
    "path": _handle_path,
}


def handle_repo_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase repo ...`` command."""

    subcommand = getattr(args, "repo_subcommand", None)
    handler = _HANDLERS.get(subcommand) if isinstance(subcommand, str) else None
    if handler is None:
        print("Usage: sase repo {init,list,log,open,path}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(handler(args))


__all__ = ["handle_repo_command"]
