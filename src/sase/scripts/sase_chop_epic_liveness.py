#!/usr/bin/env python3
"""Bounded, durable recovery scheduling for stranded epic plans."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.bead.background_store import (
    schedule_beads_sidecar_convergence,
    writable_bead_store_for_machine,
)
from sase.bead.cross_project import BeadStoreSnapshot, enabled_project_store_snapshots
from sase.bead.recovery import (
    RecoveryPublicationResult,
    publish_recovery_activation_in_store,
)
from sase.bead.recovery_submit import (
    OUTCOME_ABORTED,
    OUTCOME_CONSUMED,
    OUTCOME_REPLAYED,
    OUTCOME_SUBMITTED,
    REASON_PROC_LOOKUP_FAILED,
    REASON_SUBMIT_CONFLICT,
    REASON_UNSUPPORTED_CORE,
    RecoverySubmission,
    default_owner_machine,
    submit_recovery_launch,
)
from sase.bead._stranded_facts_members import epoch
from sase.bead.zombie import ZombieReport, load_zombie_report
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.recovery_facade import (
    RECOVERY_STATE_ABSENT,
    RecoveryClaimInspect,
    RecoveryStoreInspect,
    inspect_recovery_store,
)
from sase.notification_gates.durability import file_lock
from sase.procs.models import Proc
from sase.procs.store import get_proc
from sase.scripts._epic_liveness_state import (
    STATE_FILENAME,
    EpicLivenessCursor,
    read_cursor,
    rotate_after,
    rotate_to,
    write_cursor,
)

CHOP_NAME = "epic_liveness"
_PASS_WORK_BUDGET_SECONDS = 30.0
_SETTLEMENT_GRACE_SECONDS = 120.0
_LOCK_FILENAME = "epic_liveness.lock"


@dataclass
class _RecoveryCounts:
    """Operational counters surfaced in each scheduler result."""

    projects: int = 0
    armed: int = 0
    historical: int = 0
    owned: int = 0
    unknown: int = 0
    grace: int = 0
    consumed: int = 0
    deferred: int = 0
    submitted: int = 0
    failed: int = 0
    warnings: list[str] = field(default_factory=list)

    def fields(self) -> dict[str, int]:
        return {
            "projects": self.projects,
            "armed": self.armed,
            "historical": self.historical,
            "owned": self.owned,
            "unknown": self.unknown,
            "grace": self.grace,
            "consumed": self.consumed,
            "deferred": self.deferred,
            "submitted": self.submitted,
            "failed": self.failed,
        }


def _activation_request(project: str, now: float) -> dict[str, str]:
    armed_at = datetime.fromtimestamp(now, tz=UTC).isoformat(timespec="seconds")
    return {"project_id": project, "armed_at": armed_at}


def _arm_project(project: str, *, now: float) -> RecoveryPublicationResult:
    """Publish a create-if-absent cutoff through the machine-owned store."""

    with writable_bead_store_for_machine(
        project,
        workflow="epic_recovery_activation",
        holder="epic-recovery",
        prefer_existing_claim=True,
    ) as store:
        result = publish_recovery_activation_in_store(
            store.beads_dir,
            _activation_request(project, now),
            operation_context=store.context,
        )
        if result.published or result.local_winner:
            schedule_beads_sidecar_convergence(project)
        return result


def _activation_and_claims(
    snapshot: BeadStoreSnapshot,
    *,
    now: float,
) -> tuple[RecoveryStoreInspect | None, bool, str | None]:
    """Read an activation or arm it without scanning or launching this tick."""

    project = snapshot.origin.project_key
    beads_dir = snapshot.origin.beads_dir
    if beads_dir is None:
        return None, False, snapshot.unavailable_reason or "bead store is unavailable"
    try:
        inspected = inspect_recovery_store(str(beads_dir), project)
    except Exception as exc:  # noqa: BLE001 - isolate one damaged project.
        return None, False, f"recovery store inspection failed: {exc}"

    activation_state = inspected.activation
    if activation_state.state == RECOVERY_STATE_ABSENT:
        if inspected.claims:
            return (
                None,
                False,
                "activation is absent while recovery claims exist; refusing to re-arm",
            )
        try:
            published = _arm_project(project, now=now)
        except Exception as exc:  # noqa: BLE001 - later projects still run.
            return None, False, f"recovery activation publication failed: {exc}"
        if not published.launch_permit or published.activation is None:
            detail = published.diagnostic or published.reason
            return None, False, f"recovery activation was not confirmed: {detail}"
        return None, True, None

    activation = activation_state.activation
    if not activation_state.recovery_enabled or activation is None:
        detail = activation_state.diagnostic or activation_state.state
        return None, False, f"recovery is disabled: {detail}"
    if activation.project_id != project:
        return None, False, "recovery activation project identity does not match store"
    if epoch(activation.armed_at) is None:
        return None, False, "recovery activation cutoff has an invalid timestamp"
    return inspected, False, None


def _count_report_rows(report: ZombieReport, counts: _RecoveryCounts) -> None:
    for row in report.report.rows:
        if row.state == "owned":
            counts.owned += 1
        elif row.state == "unknown":
            counts.unknown += 1


def _claim_for_candidate(
    inspected: RecoveryStoreInspect,
    *,
    project: str,
    epic_id: str,
    close_token: str,
) -> tuple[RecoveryClaimInspect | None, str | None]:
    matches = [
        record
        for record in inspected.claims
        if record.project_id == project
        and record.epic_id == epic_id
        and record.close_token == close_token
    ]
    if not matches:
        return None, None
    if len(matches) != 1 or matches[0].claim is None:
        return None, "recovery claim is malformed or duplicated"
    return matches[0], None


def _claimed_proc(proc_id: str) -> Proc | None:
    """Return this host's proc row for a published claim, if one exists.

    A lookup failure returns ``None`` so the submission path performs its own
    guarded lookup and reports the failure.
    """

    try:
        return get_proc(proc_id)
    except Exception:  # noqa: BLE001 - the submission path reports lookup errors.
        return None


def _candidate_settled_at(report: ZombieReport, epic_id: str, close_at: float) -> float:
    terminal_at = getattr(report, "latest_owner_terminal_at", {}).get(epic_id)
    terminal_epoch = (
        float(terminal_at)
        if isinstance(terminal_at, (int, float)) and not isinstance(terminal_at, bool)
        else epoch(terminal_at)
    )
    return max(close_at, terminal_epoch) if terminal_epoch is not None else close_at


def _process_candidate(
    project: str,
    row: Any,
    report: ZombieReport,
    inspected: RecoveryStoreInspect,
    *,
    now: float,
    owner_machine: str,
    counts: _RecoveryCounts,
) -> bool:
    """Process one report candidate; return true only for a new submission."""

    if row.tier != "epic":
        counts.deferred += 1
        counts.warnings.append(
            f"{project}/{row.plan_id}: automatic recovery supports epic plans; "
            f"reported tier is {row.tier or 'unknown'}"
        )
        return False
    if not row.recovery_eligible or not row.close_token:
        if row.unknown_reason or not row.close_token:
            counts.unknown += 1
        else:
            counts.deferred += 1
            counts.warnings.append(
                f"{project}/{row.plan_id}: recovery is ineligible: "
                f"{row.recovery_reason or row.reason or 'unknown reason'}"
            )
        return False

    close_at = epoch(row.latest_descendant_closed_at)
    activation = inspected.activation.activation
    assert activation is not None
    cutoff = epoch(activation.armed_at)
    if close_at is None or cutoff is None:
        counts.unknown += 1
        counts.warnings.append(
            f"{project}/{row.plan_id}: missing or invalid close/cutoff timestamp"
        )
        return False
    if close_at <= cutoff:
        counts.historical += 1
        return False

    if now - _candidate_settled_at(report, row.plan_id, close_at) < (
        _SETTLEMENT_GRACE_SECONDS
    ):
        counts.grace += 1
        return False

    existing_claim, claim_error = _claim_for_candidate(
        inspected,
        project=project,
        epic_id=row.plan_id,
        close_token=row.close_token,
    )
    if claim_error:
        counts.unknown += 1
        counts.warnings.append(f"{project}/{row.plan_id}: {claim_error}")
        return False
    if existing_claim is not None:
        assert existing_claim.claim is not None
        if existing_claim.claim.owner_machine != owner_machine:
            counts.deferred += 1
            counts.warnings.append(
                f"{project}/{row.plan_id}: claim belongs to "
                f"{existing_claim.claim.owner_machine}; refusing transfer"
            )
            return False
        claimed_proc = _claimed_proc(existing_claim.claim.proc_id)
        if claimed_proc is not None:
            # The token already reached the proc store, so it is consumed (or
            # still in flight). Skip the publish round trip every tick; the
            # submission path would return the same no-launch outcome.
            counts.consumed += 1
            counts.warnings.append(
                f"{project}/{row.plan_id}: close token already has proc "
                f"{claimed_proc.proc_id} ({claimed_proc.status})"
            )
            return False

    submission: RecoverySubmission = submit_recovery_launch(
        project,
        row.plan_id,
        close_token=row.close_token,
        owner_machine=owner_machine,
    )
    if submission.outcome == OUTCOME_SUBMITTED:
        counts.submitted += 1
        return True
    if submission.outcome in {OUTCOME_REPLAYED, OUTCOME_CONSUMED}:
        counts.consumed += 1
        counts.warnings.append(
            f"{project}/{row.plan_id}: close token already has proc "
            f"{submission.proc_id} ({submission.outcome})"
        )
        return False
    if submission.outcome == OUTCOME_ABORTED:
        detail = submission.diagnostic or submission.reason
        if any(
            marker in submission.reason
            for marker in (
                REASON_UNSUPPORTED_CORE,
                REASON_PROC_LOOKUP_FAILED,
                REASON_SUBMIT_CONFLICT,
            )
        ):
            counts.failed += 1
            counts.warnings.append(f"{project}/{row.plan_id}: {detail}")
        else:
            counts.deferred += 1
            counts.warnings.append(f"{project}/{row.plan_id}: deferred: {detail}")
        return False

    counts.failed += 1
    counts.warnings.append(
        f"{project}/{row.plan_id}: unexpected submission outcome "
        f"{submission.outcome!r} ({submission.reason})"
    )
    return False


def _persist_cursor(
    path: Path, cursor: EpicLivenessCursor, counts: _RecoveryCounts
) -> None:
    try:
        write_cursor(path, cursor)
    except Exception as exc:  # noqa: BLE001 - next tick can safely retry.
        counts.warnings.append(f"failed to persist recovery cursor: {exc}")


def _project_key(snapshot: BeadStoreSnapshot) -> str:
    return snapshot.origin.project_key


def _run_locked(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    started = time.monotonic()
    deadline = started + _PASS_WORK_BUDGET_SECONDS
    counts = _RecoveryCounts()
    cursor_path = Path(runtime.context.state_dir) / STATE_FILENAME
    cursor = read_cursor(cursor_path)
    snapshots = sorted(
        enabled_project_store_snapshots(), key=lambda item: _project_key(item)
    )
    snapshots = rotate_to(snapshots, cursor.next_project, item_key=_project_key)
    counts.projects = len(snapshots)
    if not snapshots:
        return _finish(runtime, counts, reason="no_enabled_projects")

    now = time.time()
    activations: dict[str, RecoveryStoreInspect] = {}
    newly_armed = False
    for index, snapshot in enumerate(snapshots):
        project = _project_key(snapshot)
        if time.monotonic() >= deadline:
            counts.deferred += len(snapshots) - index
            cursor.next_project = project
            _persist_cursor(cursor_path, cursor, counts)
            return _finish(runtime, counts, reason="budget_exhausted")
        if snapshot.origin.beads_dir is None:
            counts.deferred += 1
            counts.warnings.append(
                f"{project}: {snapshot.unavailable_reason or 'bead store is not materialized'}"
            )
            continue
        inspected, armed, error = _activation_and_claims(snapshot, now=now)
        if armed:
            newly_armed = True
            counts.armed += 1
        elif error:
            counts.failed += 1
            counts.warnings.append(f"{project}: {error}")
        elif inspected is not None:
            activations[project] = inspected

    if newly_armed:
        # Any tick that establishes a rollout cutoff is report-only across all
        # projects, so a later project cannot launch a pre-existing zombie.
        cursor.next_project = _project_key(snapshots[0])
        _persist_cursor(cursor_path, cursor, counts)
        return _finish(runtime, counts, reason="activation_armed")

    owner_machine = default_owner_machine()
    submitted = False
    for index, snapshot in enumerate(snapshots):
        project = _project_key(snapshot)
        if time.monotonic() >= deadline:
            counts.deferred += len(snapshots) - index
            cursor.next_project = project
            _persist_cursor(cursor_path, cursor, counts)
            return _finish(runtime, counts, reason="budget_exhausted")
        inspected = activations.get(project)
        if inspected is None:
            continue
        try:
            report = load_zombie_report(project)
        except Exception as exc:  # noqa: BLE001 - isolate this project.
            counts.failed += 1
            counts.warnings.append(f"{project}: zombie report failed: {exc}")
            continue
        if report.collection_failed:
            counts.failed += 1
            counts.warnings.append(
                f"{project}: zombie report failed: "
                f"{report.failure_reason or 'unknown collection error'}"
            )
            continue
        _count_report_rows(report, counts)
        rows = sorted(
            (row for row in report.report.rows if row.state == "zombie"),
            key=lambda row: row.plan_id,
        )
        rows = rotate_after(
            rows,
            cursor.candidate_after.get(project),
            item_key=lambda row: row.plan_id,
        )
        for row_index, row in enumerate(rows):
            if time.monotonic() >= deadline:
                counts.deferred += len(rows) - row_index
                break
            try:
                submitted_candidate = _process_candidate(
                    project,
                    row,
                    report,
                    inspected,
                    now=now,
                    owner_machine=owner_machine,
                    counts=counts,
                )
            except Exception as exc:  # noqa: BLE001 - isolate one bad candidate.
                counts.failed += 1
                counts.warnings.append(
                    f"{project}/{row.plan_id}: candidate processing failed: {exc}"
                )
                submitted_candidate = False
            cursor.candidate_after[project] = row.plan_id
            _persist_cursor(cursor_path, cursor, counts)
            if submitted_candidate:
                submitted = True
                break
        next_index = (index + 1) % len(snapshots)
        cursor.next_project = _project_key(snapshots[next_index])
        _persist_cursor(cursor_path, cursor, counts)
        if submitted:
            break

    reason = "submission_created" if submitted else None
    if time.monotonic() >= deadline:
        reason = "budget_exhausted"
    return _finish(runtime, counts, reason=reason)


def _finish(
    runtime: BuiltinChopRuntime,
    counts: _RecoveryCounts,
    *,
    reason: str | None,
) -> ChopResultBuilder:
    for warning in counts.warnings:
        runtime.log.warning(f"[{CHOP_NAME}] {warning}")
    result = runtime.emit_summary(counts.fields(), reason=reason)
    if counts.failed:
        result.status = "check_error"
    return result


@builtin_chop(CHOP_NAME)
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    """Run one fair, bounded pass; overlap never produces a second submission."""

    if runtime.context.dry_run:
        return _finish(runtime, _RecoveryCounts(), reason="dry_run")
    state_dir = Path(runtime.context.state_dir)
    try:
        with file_lock(state_dir / _LOCK_FILENAME, timeout=0.0):
            return _run_locked(runtime)
    except Exception as exc:  # lock contention is an intentional skipped tick.
        if getattr(exc, "code", None) == "lock_timeout":
            return _finish(runtime, _RecoveryCounts(), reason="already_running")
        raise


def main() -> None:
    run_builtin_chop(CHOP_NAME)


if __name__ == "__main__":
    main()


__all__ = ["CHOP_NAME", "_run"]
