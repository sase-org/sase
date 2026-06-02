"""Command adapters for the ``sase workspace`` CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Protocol

from sase.workspace_provider.store import WorkspaceStore

from .workspace_handler_context import ProjectContext
from .workspace_handler_list import (
    handle_list as list_handle_list,
    handle_open_clean as list_handle_open_clean,
    handle_path as list_handle_path,
)
from .workspace_handler_maintenance import (
    handle_cleanup as maintenance_handle_cleanup,
    handle_repair as maintenance_handle_repair,
)
from .workspace_handler_migration import (
    handle_migrate as migration_handle_migrate,
    handle_migrate_finalize as migration_handle_migrate_finalize,
)

ProjectContextResolver = Callable[[str | None], ProjectContext]
ClaimedNums = Callable[[str], set[int]]
RemoveCheckout = Callable[[str], None]
RemoveTransitionSymlink = Callable[[ProjectContext, int], str | None]


class _CheckoutResolver(Protocol):
    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


class _StoreBuilder(Protocol):
    def __call__(
        self,
        primary_workspace_dir: str,
        *,
        policy: str,
    ) -> WorkspaceStore: ...


def handle_list_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
) -> int:
    return list_handle_list(args, resolve_project_context=resolve_project_context)


def handle_path_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    resolve_checkout: _CheckoutResolver,
) -> int:
    return list_handle_path(
        args,
        resolve_project_context=resolve_project_context,
        resolve_checkout=resolve_checkout,
    )


def handle_open_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    resolve_checkout: _CheckoutResolver,
) -> int:
    return list_handle_open_clean(
        args,
        resolve_project_context=resolve_project_context,
        resolve_checkout=resolve_checkout,
    )


def handle_cleanup_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    get_claimed_nums: ClaimedNums,
    remove_checkout_dir: RemoveCheckout,
    remove_transition: RemoveTransitionSymlink,
) -> int:
    return maintenance_handle_cleanup(
        args,
        resolve_project_context=resolve_project_context,
        get_claimed_nums=get_claimed_nums,
        remove_checkout_dir=remove_checkout_dir,
        remove_transition=remove_transition,
    )


def handle_repair_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    get_claimed_nums: ClaimedNums,
    load_config: Callable[[], dict[str, object] | None],
) -> int:
    return maintenance_handle_repair(
        args,
        resolve_project_context=resolve_project_context,
        get_claimed_nums=get_claimed_nums,
        load_config=load_config,
    )


def handle_migrate_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    build_store: _StoreBuilder,
) -> int:
    return migration_handle_migrate(
        args,
        resolve_project_context=resolve_project_context,
        build_store=build_store,
    )


def handle_migrate_finalize_command(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectContextResolver,
    build_store: _StoreBuilder,
) -> int:
    return migration_handle_migrate_finalize(
        args,
        resolve_project_context=resolve_project_context,
        build_store=build_store,
    )
