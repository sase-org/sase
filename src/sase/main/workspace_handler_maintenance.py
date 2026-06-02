"""Cleanup and repair commands for ``sase workspace``."""

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
from sase.workspace_provider.utils import ensure_workspace_checkout

from .workspace_handler_context import ConfigLoader, ProjectContext
from .workspace_handler_list import ProjectResolver, sorted_entries

ClaimedNums = Callable[[str], set[int]]
RemoveCheckout = Callable[[str], None]
RemoveTransitionSymlink = Callable[[ProjectContext, int], str | None]


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


def handle_repair(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    get_claimed_nums: ClaimedNums,
    load_config: ConfigLoader,
) -> int:
    ctx = resolve_project_context(args.project)
    registry = load_or_init_registry(ctx.store)
    claimed = get_claimed_nums(ctx.project_file)

    dropped: list[int] = []
    rematerialized: list[int] = []

    for num, entry in sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        checkout_dir = entry.checkout_dir.rstrip("/")
        if os.path.isdir(checkout_dir):
            continue
        if num in claimed:
            rematerialized.append(num)
            continue
        dropped.append(num)

    if not dropped and not rematerialized:
        print("Registry is in sync with the filesystem.")
        return 0

    for num in dropped:
        verb = "would drop" if args.dry_run else "dropping"
        print(f"{verb} stale registry entry for #{num}")
    for num in rematerialized:
        verb = "would re-materialize" if args.dry_run else "re-materializing"
        print(f"{verb} checkout for live claim #{num}")

    if args.dry_run:
        return 0

    for num in dropped:
        registry.workspaces.pop(str(num), None)
    save_registry(ctx.store, registry)

    for num in rematerialized:
        try:
            ensure_workspace_checkout(
                ctx.primary_workspace_dir,
                num,
                config=load_config(),
            )
        except RuntimeError as exc:
            print(f"  failed to re-materialize #{num}: {exc}", file=sys.stderr)

    return 0
