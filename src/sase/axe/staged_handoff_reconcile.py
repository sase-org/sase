"""Bounded host I/O for staged-handoff housekeeping.

The Rust discovery cursor covers the artifact index and a historical backfill.
Each page is checkpointed with its pending origins before adoption, so a crash
replays the same identities. The shared recovery service re-reads evidence under
the runner/CLI adoption lock; this job never runs the provider or finalizers.
"""

from __future__ import annotations

import fcntl
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from sase.core.atomic_json import write_json_marker_atomic
from sase.axe.run_agent_exec_staged_recovery import recover_staged_handoff
from sase.axe.staged_handoff_notifications import (
    held_staged_handoff_notification,
)
from sase.core.agent_scan_facade import default_agent_artifact_index_path
from sase.core.paths import sase_projects_dir
from sase.core.staged_handoff import staged_reconcile_page


@dataclass
class _StagedReconcileSummary:
    scanned: int = 0
    inspected: int = 0
    adopted: int = 0
    delivered: int = 0
    already_adopted: int = 0
    held: int = 0
    deferred: int = 0
    busy: bool = False
    errors: list[str] = field(default_factory=list)
    held_details: list[str] = field(default_factory=list)


def reconcile_staged_handoffs(
    *,
    projects_root: Path | None = None,
    index_path: Path | None = None,
    state_path: Path | None = None,
    page_limit: int = 128,
    candidate_limit: int = 32,
    time_budget: float = 60.0,
) -> _StagedReconcileSummary:
    """Reconcile one bounded page, retaining unfinished work for the next pass."""
    root = sase_projects_dir() if projects_root is None else projects_root
    index = default_agent_artifact_index_path() if index_path is None else index_path
    state_file = (
        root.parent / "axe" / "staged_handoff_reconcile.json"
        if state_path is None
        else state_path
    )
    summary = _StagedReconcileSummary()
    deadline = time.monotonic() + time_budget
    state_file.parent.mkdir(parents=True, exist_ok=True)
    # Never hold a claim lock while waiting for adoption. A second housekeeping
    # process skips immediately; CLI/runner callers use only the adoption lock.
    with state_file.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            summary.busy = True
            return summary
        try:
            state = json.loads(state_file.read_text())
            if (
                not isinstance(state, dict)
                or not isinstance(state.get("cursor"), dict)
                or not isinstance(state.get("pending"), list)
                or not all(isinstance(path, str) for path in state["pending"])
                or state.get("projects_root") != str(root)
                or (
                    "notified_holds" in state
                    and not isinstance(state.get("notified_holds"), dict)
                )
            ):
                raise ValueError("invalid reconciliation checkpoint")
        except FileNotFoundError:
            state = {"cursor": {}, "pending": [], "projects_root": str(root)}
        except (ValueError, OSError) as exc:
            summary.errors.append(f"reset unreadable reconciliation checkpoint: {exc}")
            state = {"cursor": {}, "pending": [], "projects_root": str(root)}
        state.setdefault("notified_holds", {})
        if not state["pending"] and time.monotonic() < deadline:
            try:
                page = staged_reconcile_page(
                    str(index), str(root), state["cursor"], page_limit
                )
            except ValueError as exc:
                # A corrupt cursor must not permanently strand every origin.
                summary.errors.append(str(exc))
                state["cursor"] = {}
            else:
                state["cursor"] = page["cursor"]
                state["pending"] = page["candidates"]
                summary.scanned = page["scanned"]
                summary.errors.extend(page["errors"])
            write_json_marker_atomic(state_file, state)
        while (
            state["pending"]
            and summary.inspected < candidate_limit
            and time.monotonic() < deadline
        ):
            origin = state["pending"][0]
            summary.inspected += 1
            try:
                # Reject checkpoint paths that escaped the selected artifact
                # tree (including symlink changes since discovery).
                Path(origin).resolve().relative_to(root.resolve())
                receipt_before = _adoption_receipt_snapshot(origin)
                result = recover_staged_handoff(origin, mode="automatic")
                if result.adopted:
                    state["notified_holds"].pop(origin, None)
                    if result.action == "deliver_only":
                        summary.delivered += 1
                    if result.already_adopted:
                        summary.already_adopted += 1
                    else:
                        summary.adopted += 1
                else:
                    summary.held += 1
                    summary.held_details.append(
                        f"{result.origin_agent or origin}: {result.reason or result.action}"
                    )
                    try:
                        _notify_recovery_hold(origin, receipt_before, state)
                    except Exception as exc:  # noqa: BLE001 - isolate notification IO.
                        summary.errors.append(
                            f"{origin}: failed to send staged-handoff readopt "
                            f"notification: {exc}"
                        )
            except Exception as exc:  # noqa: BLE001 - isolate each damaged origin.
                summary.errors.append(f"{origin}: {exc}")
            state["pending"].pop(0)
            write_json_marker_atomic(state_file, state)
        summary.deferred = len(state["pending"])
    return summary


def _adoption_receipt_snapshot(origin: str) -> dict | None:
    """Read a receipt snapshot without making an ineligible origin an error."""
    from sase.agent.staged_handoff import read_adoption_receipt

    try:
        return read_adoption_receipt(origin)
    except Exception:
        return None


def _notify_recovery_hold(
    origin: str,
    receipt_before: dict | None,
    state: dict,
) -> None:
    """Notify once for each new (origin, stage, reason) hold receipt."""
    notice = held_staged_handoff_notification(origin, require_current_stage=True)
    if notice is None:
        return
    receipt_after = _adoption_receipt_snapshot(origin)
    if receipt_after is None or receipt_after == receipt_before:
        return

    key = {"staged_id": notice.staged_id, "reason": notice.reason}
    notified_holds = state["notified_holds"]
    if notified_holds.get(origin) == key:
        return

    # The notification store appends rows even for a repeated notification ID,
    # so the scheduler's locked checkpoint is the deduplication authority.
    from sase.notifications.senders import notify_workflow_complete

    notify_workflow_complete(
        sender="axe",
        cl_name=None,
        success=False,
        notes=[notice.note],
    )
    notified_holds[origin] = key
