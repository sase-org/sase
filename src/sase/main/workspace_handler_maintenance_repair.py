"""Registry/filesystem repair for ``sase workspace``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Protocol

from sase.ace.patch import patch_lock
from sase.core.git_object_sharing import OBSERVATION_CLEAR
from sase.workspace_provider.git_objects import (
    GitObjectSharingError,
    classify_alternate_state,
    dissociate_checkout,
    is_git_checkout,
    repair_shared_checkout,
    status_porcelain,
)
from sase.workspace_provider.registry import load_or_init_registry, save_registry
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM
from sase.workspace_provider.utils import ensure_workspace_checkout

from ._workspace_handler_maintenance_shared import ClaimedNums, has_live_occupant
from .workspace_handler_context import ConfigLoader, ProjectContext
from .workspace_handler_list import ProjectResolver, sorted_entries

__all__ = ["handle_repair"]


class _AlternateStateLike(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def sase_owned(self) -> bool: ...

    @property
    def detail(self) -> str: ...


@dataclass(frozen=True)
class _AlternateRepairEligibility:
    ok: bool
    reason: str
    state: _AlternateStateLike | None = None


def _refusal_repair_plan(
    project: str,
    clear_refusal: str | None,
    *,
    dry_run: bool,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Plan (and optionally apply) nested-preservation refusal clears.

    *clear_refusal* is ``None`` (auto-clear stale records during repair),
    ``"*"`` (``--clear-refusal`` without a number), or a workspace number
    string for a force-clear.
    """
    from sase.workspace_provider.slot_refusal import (
        SlotRefusalRecord,
        clear_refusal as force_clear_refusal,
        clear_stale_refusals,
        list_refusals,
        nested_repo_still_refuses,
    )

    clears: list[tuple[int, str]] = []
    skips: list[tuple[int, str]] = []
    if clear_refusal not in {None, "*"}:
        try:
            workspace_num = int(clear_refusal)
        except (TypeError, ValueError):
            skips.append((0, f"invalid workspace number {clear_refusal!r}"))
            return clears, skips
        records: dict[int, SlotRefusalRecord] = {
            record.workspace_num: record for record in list_refusals(project)
        }
        record = records.get(workspace_num)
        if record is None:
            skips.append((workspace_num, "no standing nested-preservation refusal"))
            return clears, skips
        if not dry_run:
            force_clear_refusal(project, workspace_num)
        clears.append((workspace_num, record.nested_repo))
        return clears, skips

    stale = []
    standing = []
    for record in list_refusals(project):
        if nested_repo_still_refuses(record.nested_repo):
            standing.append(record)
        else:
            stale.append(record)
    if not dry_run:
        clear_stale_refusals(project)
        if clear_refusal is None:
            # Repair always drops refusals that no longer apply.
            pass
    for record in stale:
        clears.append((record.workspace_num, record.nested_repo))
    if clear_refusal == "*":
        for record in standing:
            skips.append(
                (
                    record.workspace_num,
                    "nested repo is still dirty; pass "
                    f"--clear-refusal {record.workspace_num} to force-clear",
                )
            )
    return clears, skips


def _status_failure_detail(status: subprocess.CompletedProcess[str]) -> str:
    if status.returncode == 0:
        return ""
    return (status.stderr or status.stdout or "").strip() or "status failed"


def _alternate_repair_eligibility(
    ctx: ProjectContext,
    *,
    workspace_num: int,
    checkout_dir: str,
    claimed: set[int],
) -> _AlternateRepairEligibility:
    if workspace_num == PRIMARY_WORKSPACE_NUM:
        return _AlternateRepairEligibility(False, "primary checkout")
    if workspace_num in claimed:
        return _AlternateRepairEligibility(False, "live RUNNING claim")
    if not os.path.isdir(checkout_dir):
        return _AlternateRepairEligibility(False, "missing checkout")
    if has_live_occupant(checkout_dir):
        return _AlternateRepairEligibility(False, "live occupant")
    if not is_git_checkout(checkout_dir):
        return _AlternateRepairEligibility(False, "not a Git checkout")

    try:
        state = classify_alternate_state(
            checkout_dir,
            primary_checkout_dir=ctx.primary_workspace_dir,
        )
    except GitObjectSharingError as exc:
        return _AlternateRepairEligibility(
            False,
            f"alternate inspection failed: {exc}",
        )

    status = status_porcelain(checkout_dir)
    status_detail = _status_failure_detail(status)
    if status_detail and not state.sase_owned:
        return _AlternateRepairEligibility(
            False,
            f"could not read git status: {status_detail}",
            state,
        )
    if not status_detail and status.stdout.strip():
        return _AlternateRepairEligibility(False, "dirty checkout", state)

    return _AlternateRepairEligibility(True, "eligible", state)


def _alternate_repair_action(
    ctx: ProjectContext,
    state: _AlternateStateLike,
) -> str | None:
    if ctx.store.share_git_objects:
        if state.status in {"stale", "broken"} and state.sase_owned:
            return "repoint"
        if state.status == "broken":
            return "failure"
        if state.status == "unexpected":
            return "skip"
        return None
    if state.sase_owned and state.status != "absent":
        return "dissociate"
    return None


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
    refusal_clears, refusal_skips = _refusal_repair_plan(
        ctx.project_name,
        getattr(args, "clear_refusal", None),
        dry_run=bool(args.dry_run),
    )

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

        eligibility = _alternate_repair_eligibility(
            ctx,
            workspace_num=num,
            checkout_dir=checkout_dir,
            claimed=claimed,
        )
        state = eligibility.state
        if state is None:
            if eligibility.reason.startswith("alternate inspection failed"):
                alternate_failures.append((num, eligibility.reason))
            elif eligibility.reason != "not a Git checkout":
                alternate_skips.append((num, eligibility.reason))
            continue

        action = _alternate_repair_action(ctx, state)
        if action == "repoint":
            if eligibility.ok:
                repoint.append((num, checkout_dir))
            else:
                alternate_skips.append((num, eligibility.reason))
        elif action == "dissociate":
            if eligibility.ok:
                dissociate.append((num, checkout_dir))
            else:
                alternate_skips.append((num, eligibility.reason))
        elif action == "failure":
            alternate_failures.append((num, state.detail or "broken alternate"))
        elif action == "skip":
            alternate_skips.append(
                (num, state.detail or "alternate is not SASE-managed")
            )

    if (
        not dropped
        and not rematerialized
        and not repoint
        and not dissociate
        and not alternate_failures
        and not alternate_skips
        and not refusal_clears
        and not refusal_skips
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
    for num, nested in refusal_clears:
        verb = "would clear" if args.dry_run else "clearing"
        print(f"{verb} nested-preservation refusal for #{num}: {nested}")
    for num, detail in refusal_skips:
        print(f"skipping refusal #{num}: {detail}")

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
        with patch_lock(ctx.project_file):
            locked = _alternate_repair_eligibility(
                ctx,
                workspace_num=num,
                checkout_dir=checkout_dir,
                claimed=get_claimed_nums(ctx.project_file),
            )
            action = (
                None
                if locked.state is None
                else _alternate_repair_action(ctx, locked.state)
            )
            if not locked.ok or action != "repoint":
                reason = locked.reason if not locked.ok else "no longer needs repair"
                print(f"  skipped #{num}: {reason} after locked recheck")
                continue
            try:
                result = repair_shared_checkout(
                    ctx.primary_workspace_dir,
                    checkout_dir,
                    fresh_claim_status=OBSERVATION_CLEAR,
                    fresh_occupant_status=OBSERVATION_CLEAR,
                )
            except GitObjectSharingError as exc:
                print(f"  failed to repair #{num}: {exc}", file=sys.stderr)
                failed = True
                continue
        print(f"  repaired #{num}: {result.before_bytes} -> {result.after_bytes} bytes")

    for num, checkout_dir in dissociate:
        with patch_lock(ctx.project_file):
            locked = _alternate_repair_eligibility(
                ctx,
                workspace_num=num,
                checkout_dir=checkout_dir,
                claimed=get_claimed_nums(ctx.project_file),
            )
            action = (
                None
                if locked.state is None
                else _alternate_repair_action(ctx, locked.state)
            )
            if not locked.ok or action != "dissociate":
                reason = (
                    locked.reason if not locked.ok else "no longer needs dissociation"
                )
                print(f"  skipped #{num}: {reason} after locked recheck")
                continue
            try:
                result = dissociate_checkout(
                    ctx.primary_workspace_dir,
                    checkout_dir,
                    fresh_claim_status=OBSERVATION_CLEAR,
                    fresh_occupant_status=OBSERVATION_CLEAR,
                )
            except GitObjectSharingError as exc:
                print(f"  failed to dissociate #{num}: {exc}", file=sys.stderr)
                failed = True
                continue
        print(
            f"  dissociated #{num}: {result.before_bytes} -> {result.after_bytes} bytes"
        )

    return 1 if failed else 0
