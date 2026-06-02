"""Handler implementation for the ``sase workspace`` CLI subcommand."""

from __future__ import annotations

import argparse
import sys

from sase.config.core import load_merged_config
from sase.core.project_lifecycle_facade import (
    apply_project_lifecycle_update,
    read_project_lifecycle_from_content,
)
from sase.running_field._operations import get_claimed_workspaces
from sase.workflows.utils import get_project_file_path
from sase.workspace_provider.registry import (
    WorkspaceEntry,
    WorkspaceRegistry,
    load_or_init_registry,
    save_registry,
)
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)
from sase.workspace_provider.utils import (
    ensure_workspace_checkout,
    parse_bare_repo_dir,
    parse_workspace_dir,
)

from .workspace_handler_context import (
    ProjectContext,
    resolve_project_context as context_resolve_project_context,
)
from .workspace_handler_list import (
    handle_list as list_handle_list,
    handle_open_clean as list_handle_open_clean,
    handle_path as list_handle_path,
    resolve_checkout_path as list_resolve_checkout_path,
)
from .workspace_handler_maintenance import (
    claimed_nums as maintenance_claimed_nums,
    handle_cleanup as maintenance_handle_cleanup,
    handle_repair as maintenance_handle_repair,
    remove_checkout as maintenance_remove_checkout,
    remove_transition_symlink as maintenance_remove_transition_symlink,
)
from .workspace_handler_migration import (
    build_store_with_policy as migration_build_store_with_policy,
    handle_migrate as migration_handle_migrate,
    handle_migrate_finalize as migration_handle_migrate_finalize,
)

_ProjectContext = ProjectContext


def _resolve_project_context(project: str | None) -> _ProjectContext:
    return context_resolve_project_context(
        project,
        load_config=load_merged_config,
        read_project_lifecycle=read_project_lifecycle_from_content,
        apply_project_lifecycle=apply_project_lifecycle_update,
    )


def _claimed_nums(project_file: str) -> set[int]:
    return maintenance_claimed_nums(
        project_file,
        get_claimed_workspaces=get_claimed_workspaces,
    )


def _resolve_checkout_path(
    ctx: _ProjectContext,
    workspace_num: int,
    *,
    materialize: bool,
) -> str:
    return list_resolve_checkout_path(
        ctx,
        workspace_num,
        materialize=materialize,
        load_config=load_merged_config,
    )


def _remove_checkout(checkout_dir: str) -> None:
    return maintenance_remove_checkout(checkout_dir)


def _remove_transition_symlink(
    ctx: _ProjectContext,
    workspace_num: int,
) -> str | None:
    return maintenance_remove_transition_symlink(ctx, workspace_num)


def _build_store_with_policy(
    primary_workspace_dir: str,
    *,
    policy: str,
) -> WorkspaceStore:
    return migration_build_store_with_policy(
        primary_workspace_dir,
        policy=policy,
        load_config=load_merged_config,
    )


def _handle_list(args: argparse.Namespace) -> int:
    return list_handle_list(args, resolve_project_context=_resolve_project_context)


def _handle_path(args: argparse.Namespace) -> int:
    return list_handle_path(
        args,
        resolve_project_context=_resolve_project_context,
        resolve_checkout=_resolve_checkout_path,
    )


def _handle_open(args: argparse.Namespace) -> int:
    return _handle_open_clean(args)


def _handle_open_clean(args: argparse.Namespace) -> int:
    return list_handle_open_clean(
        args,
        resolve_project_context=_resolve_project_context,
        resolve_checkout=_resolve_checkout_path,
    )


def _handle_cleanup(args: argparse.Namespace) -> int:
    return maintenance_handle_cleanup(
        args,
        resolve_project_context=_resolve_project_context,
        get_claimed_nums=_claimed_nums,
        remove_checkout_dir=_remove_checkout,
        remove_transition=_remove_transition_symlink,
    )


def _handle_repair(args: argparse.Namespace) -> int:
    return maintenance_handle_repair(
        args,
        resolve_project_context=_resolve_project_context,
        get_claimed_nums=_claimed_nums,
        load_config=load_merged_config,
    )


def _handle_migrate(args: argparse.Namespace) -> int:
    if args.finalize:
        return _handle_migrate_finalize(args)
    return migration_handle_migrate(
        args,
        resolve_project_context=_resolve_project_context,
        build_store=_build_store_with_policy,
    )


def _handle_migrate_finalize(args: argparse.Namespace) -> int:
    return migration_handle_migrate_finalize(
        args,
        resolve_project_context=_resolve_project_context,
        build_store=_build_store_with_policy,
    )


_HANDLERS = {
    "list": _handle_list,
    "path": _handle_path,
    "open": _handle_open,
    "cleanup": _handle_cleanup,
    "repair": _handle_repair,
    "migrate": _handle_migrate,
}


def handle_workspace_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase workspace ...`` command to its handler."""
    sub = getattr(args, "workspace_subcommand", None)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print(
            "Usage: sase workspace {list,path,open,cleanup,repair,migrate}",
            file=sys.stderr,
        )
        sys.exit(2)
    sys.exit(handler(args))
