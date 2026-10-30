"""Stale-checkout cleanup for ``sase workspace``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from typing import Protocol

from sase.workspace_provider.registry import (
    WorkspaceEntry,
    load_or_init_registry,
    save_registry,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

from ._workspace_handler_maintenance_shared import ClaimedNums
from .workspace_handler_context import ProjectContext
from .workspace_handler_list import ProjectResolver, sorted_entries

RemoveCheckout = Callable[[str], None]
RemoveTransitionSymlink = Callable[[ProjectContext, int], str | None]

__all__ = [
    "RemoveCheckout",
    "RemoveTransitionSymlink",
    "claimed_nums",
    "handle_cleanup",
    "remove_checkout",
    "remove_transition_symlink",
]


class _WorkspaceClaimLike(Protocol):
    workspace_num: int


def claimed_nums(
    project_file: str,
    *,
    get_claimed_workspaces: Callable[[str], Iterable[_WorkspaceClaimLike]],
) -> set[int]:
    return {claim.workspace_num for claim in get_claimed_workspaces(project_file)}


def _is_stale(
    entry: WorkspaceEntry,
    *,
    ttl_seconds: float,
    now: float,
) -> bool:
    if entry.pinned:
        return False
    return (now - entry.last_used_at) > ttl_seconds


def remove_checkout(checkout_dir: str) -> None:
    path = checkout_dir.rstrip("/")
    if not path:
        return
    if os.path.islink(path):
        try:
            os.unlink(path)
        except OSError:
            pass
        return
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def remove_transition_symlink(ctx: ProjectContext, workspace_num: int) -> str | None:
    """Remove any ``<primary>_<num>`` symlink left behind by migrations.

    Returns the symlink path that was removed, or ``None`` when there is
    nothing to do.
    """
    if workspace_num <= 1:
        return None
    if ctx.store.root_policy == "adjacent":
        return None
    base = ctx.primary_workspace_dir.rstrip("/")
    candidate = f"{base}_{workspace_num}"
    if os.path.islink(candidate):
        try:
            os.unlink(candidate)
        except OSError:
            return None
        return candidate
    return None


def handle_cleanup(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    get_claimed_nums: ClaimedNums,
    remove_checkout_dir: RemoveCheckout,
    remove_transition: RemoveTransitionSymlink,
) -> int:
    ctx = resolve_project_context(args.project)
    if not args.stale:
        print(
            "sase workspace cleanup currently requires -s/--stale.",
            file=sys.stderr,
        )
        return 2

    registry = load_or_init_registry(ctx.store)
    ttl_days = ctx.store.cleanup_ttl_days
    ttl_seconds = float(ttl_days) * 86400.0
    now = time.time()
    claimed = get_claimed_nums(ctx.project_file)

    planned: list[tuple[int, WorkspaceEntry]] = []
    for num, entry in sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        if num in claimed:
            continue
        if not args.include_shares and entry.role == "share":
            continue
        if not _is_stale(entry, ttl_seconds=ttl_seconds, now=now):
            continue
        planned.append((num, entry))

    if not planned:
        print("No stale managed checkouts to remove.")
        return 0

    for num, entry in planned:
        verb = "would remove" if args.dry_run else "removing"
        print(f"{verb} #{num}: {entry.checkout_dir}")

    if args.dry_run:
        return 0

    for num, entry in planned:
        remove_checkout_dir(entry.checkout_dir)
        symlink = remove_transition(ctx, num)
        if symlink:
            print(f"  removed transition symlink: {symlink}")
        registry.workspaces.pop(str(num), None)

    save_registry(ctx.store, registry)
    return 0
