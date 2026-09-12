"""Cleanup and repair commands for ``sase workspace``."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from sase.ace.patch import patch_lock
from sase.workspace_provider.git_objects import (
    GitObjectSharingError,
    checkout_object_bytes,
    classify_alternate_state,
    compact_checkout,
    dissociate_checkout,
    is_git_checkout,
    repair_shared_checkout,
    status_porcelain,
)
from sase.workspace_provider.occupant import read_occupant_record
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


@dataclass(frozen=True)
class _CompactEligibility:
    ok: bool
    reason: str
    before_bytes: int = 0
    alternate_status: str = ""


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


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _has_live_occupant(checkout_dir: str) -> bool:
    record = read_occupant_record(checkout_dir)
    return record is not None and _pid_is_alive(record.pid)


def _compact_eligibility(
    ctx: ProjectContext,
    *,
    workspace_num: int,
    checkout_dir: str,
    claimed: set[int],
) -> _CompactEligibility:
    if workspace_num == PRIMARY_WORKSPACE_NUM:
        return _CompactEligibility(False, "primary checkout")
    if workspace_num in claimed:
        return _CompactEligibility(False, "live RUNNING claim")
    if not os.path.isdir(checkout_dir):
        return _CompactEligibility(False, "missing checkout")
    if _has_live_occupant(checkout_dir):
        return _CompactEligibility(False, "live occupant")
    if not is_git_checkout(checkout_dir):
        return _CompactEligibility(False, "not a Git checkout")

    status = status_porcelain(checkout_dir)
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "").strip() or "status failed"
        return _CompactEligibility(False, f"could not read git status: {detail}")
    if status.stdout.strip():
        return _CompactEligibility(False, "dirty checkout")

    try:
        state = classify_alternate_state(
            checkout_dir,
            primary_checkout_dir=ctx.primary_workspace_dir,
        )
    except GitObjectSharingError as exc:
        return _CompactEligibility(False, f"alternate inspection failed: {exc}")

    if state.status == "unexpected" or (
        state.status == "broken" and not state.sase_owned
    ):
        return _CompactEligibility(False, f"{state.status} alternate: {state.detail}")

    try:
        before = checkout_object_bytes(checkout_dir)
    except GitObjectSharingError as exc:
        return _CompactEligibility(False, f"object measurement failed: {exc}")

    return _CompactEligibility(
        True,
        "eligible",
        before_bytes=before,
        alternate_status=state.status,
    )


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


def handle_compact(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    get_claimed_nums: ClaimedNums,
) -> int:
    ctx = resolve_project_context(args.project)
    registry = load_or_init_registry(ctx.store)
    claimed = get_claimed_nums(ctx.project_file)

    attempted = False
    failed = False
    any_rows = False
    requested = set(getattr(args, "workspace_nums", None) or [])

    for num, entry in sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        if requested and num not in requested:
            continue
        checkout_dir = entry.checkout_dir.rstrip("/")
        any_rows = True
        eligibility = _compact_eligibility(
            ctx,
            workspace_num=num,
            checkout_dir=checkout_dir,
            claimed=claimed,
        )
        if not eligibility.ok:
            print(f"skipped #{num}: {eligibility.reason} ({checkout_dir})")
            continue

        if args.dry_run:
            print(
                f"would compact #{num}: {checkout_dir} "
                f"(local objects {eligibility.before_bytes} bytes; "
                f"alternate {eligibility.alternate_status})"
            )
            continue

        attempted = True
        with patch_lock(ctx.project_file):
            locked_claimed = get_claimed_nums(ctx.project_file)
            locked = _compact_eligibility(
                ctx,
                workspace_num=num,
                checkout_dir=checkout_dir,
                claimed=locked_claimed,
            )
            if not locked.ok:
                print(f"skipped #{num}: {locked.reason} after locked recheck")
                continue
            try:
                result = compact_checkout(ctx.primary_workspace_dir, checkout_dir)
            except GitObjectSharingError as exc:
                print(f"failed #{num}: {exc}", file=sys.stderr)
                failed = True
                continue
        print(
            f"compacted #{num}: {checkout_dir} "
            f"({result.before_bytes} -> {result.after_bytes} bytes, "
            f"reclaimed {result.reclaimed_bytes} bytes)"
        )

    if not any_rows:
        if requested:
            nums = ", ".join(f"#{num}" for num in sorted(requested))
            print(f"No matching registry-owned numbered checkouts to compact: {nums}.")
        else:
            print("No registry-owned numbered checkouts to compact.")
    elif args.dry_run:
        print("Dry run complete; no checkouts changed.")
    elif not attempted:
        print("No eligible checkouts to compact.")

    return 1 if failed else 0


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
    repoint: list[tuple[int, str]] = []
    dissociate: list[tuple[int, str]] = []
    alternate_failures: list[tuple[int, str]] = []
    alternate_skips: list[tuple[int, str]] = []

    for num, entry in sorted_entries(registry):
        if num == PRIMARY_WORKSPACE_NUM:
            continue
        checkout_dir = entry.checkout_dir.rstrip("/")
        if not os.path.isdir(checkout_dir):
            if num in claimed:
                rematerialized.append(num)
                continue
            dropped.append(num)
            continue

        if not is_git_checkout(checkout_dir):
            continue
        try:
            state = classify_alternate_state(
                checkout_dir,
                primary_checkout_dir=ctx.primary_workspace_dir,
            )
        except GitObjectSharingError as exc:
            alternate_failures.append((num, str(exc)))
            continue

        if ctx.store.share_git_objects:
            if state.status in {"stale", "broken"} and state.sase_owned:
                repoint.append((num, checkout_dir))
            elif state.status == "broken":
                alternate_failures.append((num, state.detail or "broken alternate"))
            elif state.status == "unexpected":
                alternate_skips.append(
                    (num, state.detail or "alternate is not SASE-managed")
                )
        elif state.sase_owned and state.status != "absent":
            dissociate.append((num, checkout_dir))

    if (
        not dropped
        and not rematerialized
        and not repoint
        and not dissociate
        and not alternate_failures
        and not alternate_skips
    ):
        print("Registry is in sync with the filesystem.")
        return 0

    for num in dropped:
        verb = "would drop" if args.dry_run else "dropping"
        print(f"{verb} stale registry entry for #{num}")
    for num in rematerialized:
        verb = "would re-materialize" if args.dry_run else "re-materializing"
        print(f"{verb} checkout for live claim #{num}")
    for num, checkout_dir in repoint:
        verb = "would repoint" if args.dry_run else "repointing"
        print(f"{verb} shared object alternate for #{num}: {checkout_dir}")
    for num, checkout_dir in dissociate:
        verb = "would dissociate" if args.dry_run else "dissociating"
        print(f"{verb} shared object alternate for #{num}: {checkout_dir}")
    for num, detail in alternate_skips:
        print(f"skipping #{num}: {detail}")
    for num, detail in alternate_failures:
        print(f"failed #{num}: {detail}", file=sys.stderr)

    if args.dry_run:
        return 1 if alternate_failures else 0

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

    failed = bool(alternate_failures)
    for num, checkout_dir in repoint:
        try:
            result = repair_shared_checkout(ctx.primary_workspace_dir, checkout_dir)
        except GitObjectSharingError as exc:
            print(f"  failed to repair #{num}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"  repaired #{num}: {result.before_bytes} -> {result.after_bytes} bytes")

    for num, checkout_dir in dissociate:
        try:
            result = dissociate_checkout(checkout_dir)
        except GitObjectSharingError as exc:
            print(f"  failed to dissociate #{num}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(
            f"  dissociated #{num}: {result.before_bytes} -> {result.after_bytes} bytes"
        )

    return 1 if failed else 0
