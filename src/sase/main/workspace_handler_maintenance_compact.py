"""Object-sharing compaction for ``sase workspace``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from sase.ace.patch import patch_lock
from sase.core.git_object_sharing import OBSERVATION_CLEAR
from sase.workspace_provider.git_objects import (
    GitObjectSharingError,
    checkout_object_bytes,
    classify_alternate_state,
    compact_checkout,
    is_git_checkout,
    status_porcelain,
)
from sase.workspace_provider.registry import load_or_init_registry
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

from ._workspace_handler_maintenance_shared import ClaimedNums, has_live_occupant
from .workspace_handler_context import ProjectContext
from .workspace_handler_list import ProjectResolver, sorted_entries

__all__ = ["handle_compact"]


@dataclass(frozen=True)
class _CompactEligibility:
    ok: bool
    reason: str
    before_bytes: int = 0
    alternate_status: str = ""


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
    if has_live_occupant(checkout_dir):
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


def _compact_row(
    workspace_num: int,
    checkout_dir: str,
    status: str,
    *,
    reason: str,
    before_bytes: int = 0,
    after_bytes: int = 0,
    reclaimed_bytes: int = 0,
    alternate_status: str = "",
    exit_code: int | None = None,
) -> dict[str, Any]:
    return {
        "workspace_num": workspace_num,
        "checkout_dir": checkout_dir,
        "status": status,
        "reason": reason,
        "before_bytes": int(before_bytes),
        "after_bytes": int(after_bytes),
        "reclaimed_bytes": int(reclaimed_bytes),
        "alternate_status": alternate_status,
        "exit_code": exit_code,
    }


def _compact_result_payload(
    ctx: ProjectContext,
    *,
    apply: bool,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = sum(1 for row in rows if row["status"] == "failed")
    return {
        "project": ctx.project_name,
        "apply": apply,
        "changed": any(row["status"] == "compacted" for row in rows),
        "errors": errors,
        "skipped": sum(1 for row in rows if row["status"] == "skipped"),
        "planned": sum(1 for row in rows if row["status"] == "planned"),
        "compacted": sum(1 for row in rows if row["status"] == "compacted"),
        "reclaimed_bytes": sum(int(row["reclaimed_bytes"]) for row in rows),
        "rows": rows,
    }


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
    json_output = bool(getattr(args, "json", False))
    rows: list[dict[str, Any]] = []

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
            rows.append(
                _compact_row(
                    num,
                    checkout_dir,
                    "skipped",
                    reason=eligibility.reason,
                    before_bytes=eligibility.before_bytes,
                    alternate_status=eligibility.alternate_status,
                )
            )
            if not json_output:
                print(f"skipped #{num}: {eligibility.reason} ({checkout_dir})")
            continue

        if args.dry_run:
            rows.append(
                _compact_row(
                    num,
                    checkout_dir,
                    "planned",
                    reason="eligible",
                    before_bytes=eligibility.before_bytes,
                    reclaimed_bytes=eligibility.before_bytes,
                    alternate_status=eligibility.alternate_status,
                )
            )
            if not json_output:
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
                rows.append(
                    _compact_row(
                        num,
                        checkout_dir,
                        "skipped",
                        reason=f"{locked.reason} after locked recheck",
                        before_bytes=locked.before_bytes,
                        alternate_status=locked.alternate_status,
                    )
                )
                if not json_output:
                    print(f"skipped #{num}: {locked.reason} after locked recheck")
                continue
            try:
                # The locked recheck above just re-proved no live RUNNING
                # claim and no live occupant, which is the observation the
                # core requires before it will mutate the dependency.
                result = compact_checkout(
                    ctx.primary_workspace_dir,
                    checkout_dir,
                    fresh_claim_status=OBSERVATION_CLEAR,
                    fresh_occupant_status=OBSERVATION_CLEAR,
                )
            except GitObjectSharingError as exc:
                rows.append(
                    _compact_row(
                        num,
                        checkout_dir,
                        "failed",
                        reason=str(exc),
                        before_bytes=locked.before_bytes,
                        alternate_status=locked.alternate_status,
                        exit_code=1,
                    )
                )
                if not json_output:
                    print(f"failed #{num}: {exc}", file=sys.stderr)
                failed = True
                continue
        rows.append(
            _compact_row(
                num,
                checkout_dir,
                "compacted",
                reason=result.status,
                before_bytes=result.before_bytes,
                after_bytes=result.after_bytes,
                reclaimed_bytes=result.reclaimed_bytes,
            )
        )
        if not json_output:
            print(
                f"compacted #{num}: {checkout_dir} "
                f"({result.before_bytes} -> {result.after_bytes} bytes, "
                f"reclaimed {result.reclaimed_bytes} bytes)"
            )

    if json_output:
        print(
            json.dumps(
                _compact_result_payload(
                    ctx,
                    apply=not args.dry_run,
                    rows=rows,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    elif not any_rows:
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
