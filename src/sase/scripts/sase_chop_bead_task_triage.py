#!/usr/bin/env python3
"""Raise and reconcile the one pending gate each live bead may have.

A task bead is either ready — awaiting a ``TaskTriage`` decision — or snoozed,
awaiting a ``BeadSnooze`` wake. A flag bead whose removal thresholds have both
passed awaits a ``FlagTriage`` decision. All three gate kinds are reconciled
here, in one lane state and under one lock, because "which gate does this bead
have" is a single question: a second chop owning a second kind could only race
this one into giving a bead two pending gates.
"""

from __future__ import annotations

from pathlib import Path

import sase
from sase.bead.config import get_task_triage_min_plus_ones
from sase.bead.flag_gate import FLAG_TRIAGE_KIND, create_flag_triage_gate
from sase.bead.gate_lookup import find_pending_bead_gates
from sase.bead.model import Issue, SnoozeRecord
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND, create_bead_snooze_gate
from sase.bead.task_gate import TASK_TRIAGE_KIND, create_task_triage_gate
from sase.bead.task_launch import active_task_launch_bead_ids
from sase.bead.task_triage_policy import task_gate_suppressed
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import time as core_time
from sase.notification_gates.durability import file_lock
from sase.scripts._bead_task_triage_gates import (
    REQUEST_ID_PREFIXES as _REQUEST_ID_PREFIXES,
    GateState as _GateState,
    NotificationSnoozeIndex as _NotificationSnoozeIndex,
    cancel_pending_gate as _cancel_pending_gate_impl,
    create_gate as _create_gate_impl,
    expected_gate_kind as _expected_gate_kind_impl,
    gate_notification_id as _gate_notification_id_impl,
    gate_state as _gate_state_impl,
    heal_snoozed_notification as _heal_snoozed_notification_impl,
    presentation_fingerprint as _presentation_fingerprint_impl,
    request_id as _request_id_impl,
)
from sase.scripts._bead_gate_projects import (
    ProjectInventory as _ProjectInventory,
    coerce_project_inventory as _coerce_project_inventory,
    enabled_project_stores as _enabled_project_stores_impl,
    project_display_name as _project_display_name,
)
from sase.scripts._bead_task_triage_state import (
    STATE_SCHEMA_VERSION as _STATE_SCHEMA_VERSION,
    ProjectState as _ProjectState,
    gateable_beads as _gateable_beads,
    write_state as _write_state_impl,
)
from sase.scripts._bead_task_triage_state import read_state as _read_state_impl

_STATE_FILENAME = "bead_task_triage.json"
_LOCK_FILENAME = "bead_task_triage.lock"

# Bumped whenever a gate preview or notification-note renderer changes shape, so
# the reconciler replaces pending gates still advertising the superseded one.
_PRESENTATION_FORMAT_VERSION = 2

# Bumped whenever the trusted TaskTriage, BeadSnooze, or FlagTriage interaction
# contract changes shape, so pending gates still exposing old option inputs are
# replaced.
_GATE_CONTRACT_VERSION = 2

_GATE_KINDS = (TASK_TRIAGE_KIND, BEAD_SNOOZE_KIND, FLAG_TRIAGE_KIND)


def _enabled_project_stores(log: ChopLogger) -> _ProjectInventory:
    """Keep the log-only signature so existing test doubles still patch this name."""
    return _enabled_project_stores_impl(log, chop="bead_task_triage")


def _read_state(path: Path) -> dict[str, _ProjectState]:
    return _read_state_impl(path, gate_kinds=_GATE_KINDS)


def _write_state(path: Path, projects: dict[str, _ProjectState]) -> None:
    _write_state_impl(path, projects)


def _expected_gate_kind(issue: Issue) -> str:
    return _expected_gate_kind_impl(issue)


def _request_id(project_name: str, bead_id: str, generation: int, kind: str) -> str:
    return _request_id_impl(project_name, bead_id, generation, kind)


def _presentation_fingerprint(issue: Issue) -> str:
    return _presentation_fingerprint_impl(
        issue,
        format_version=_PRESENTATION_FORMAT_VERSION,
        gate_contract_version=_GATE_CONTRACT_VERSION,
        # Gateable flag beads are always due (see `_gateable_beads`), so this
        # is not a second due-ness comparison -- just threading the one
        # already-known state into the fingerprint.
        flag_due_state="due" if issue.flag is not None else None,
    )


def _gate_state(kind: str, request_id: str) -> _GateState:
    return _gate_state_impl(kind, request_id)


def _cancel_pending_gate(
    kind: str,
    request_id: str,
    *,
    reason: str = "task_bead_no_longer_ready",
) -> bool:
    return _cancel_pending_gate_impl(kind, request_id, reason=reason)


def _gate_notification_id(kind: str, request_id: str) -> str | None:
    return _gate_notification_id_impl(kind, request_id)


def _heal_snoozed_notification(
    request_id: str,
    snooze: SnoozeRecord | None,
    index: _NotificationSnoozeIndex,
) -> bool:
    return _heal_snoozed_notification_impl(
        request_id,
        snooze,
        index,
        notification_id_for=_gate_notification_id,
    )


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    deferred: int = 0,
    resnoozed: int = 0,
    suppressed: int = 0,
    swept_projects: int = 0,
    untracked_canceled: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
            "deferred": deferred,
            "resnoozed": resnoozed,
            "suppressed": suppressed,
            "swept_projects": swept_projects,
            "untracked_canceled": untracked_canceled,
        },
        reason=reason,
    )


def _create_gate(
    kind: str,
    *,
    request_id: str,
    bead_id: str,
    project_name: str,
    issue: Issue,
) -> None:
    _create_gate_impl(
        kind,
        request_id=request_id,
        bead_id=bead_id,
        project_name=project_name,
        issue=issue,
        task_gate_factory=create_task_triage_gate,
        flag_gate_factory=create_flag_triage_gate,
        snooze_gate_factory=create_bead_snooze_gate,
    )


def _sweep_inactive_state_projects(
    projects: dict[str, _ProjectState],
    *,
    reconciled_projects: set[str],
    skipped_projects: set[str],
    log: ChopLogger,
) -> tuple[int, int, bool]:
    """Cancel and drop state for projects absent from this healthy inventory pass."""
    canceled = 0
    swept_projects = 0
    state_changed = False
    inactive_projects = set(projects) - reconciled_projects - skipped_projects
    for project_name in sorted(inactive_projects):
        project_state = projects[project_name]
        failed = False
        for bead_id, request_id in sorted(project_state.gates.items()):
            kind = project_state.kinds.get(bead_id, TASK_TRIAGE_KIND)
            try:
                gate_state = _gate_state(kind, request_id)
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                log.warning(
                    f"[bead_task_triage] Failed to inspect inactive-project "
                    f"gate {request_id} for "
                    f"{_project_display_name(project_name)}: {exc}"
                )
                failed = True
                continue
            if gate_state != "pending":
                continue
            try:
                was_canceled = _cancel_pending_gate(
                    kind,
                    request_id,
                    reason="project_no_longer_enabled",
                )
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                log.warning(
                    f"[bead_task_triage] Failed to cancel inactive-project "
                    f"gate {request_id} for "
                    f"{_project_display_name(project_name)}: {exc}"
                )
                failed = True
                continue
            canceled += int(was_canceled)
        if failed:
            continue
        del projects[project_name]
        swept_projects += 1
        state_changed = True
    return canceled, swept_projects, state_changed


def _sweep_untracked_produced_gates(
    projects: dict[str, _ProjectState],
    *,
    skipped_projects: set[str],
    log: ChopLogger,
) -> int:
    """Cancel pending gates this chop produced but no longer records in state."""
    expected_request_ids = {
        request_id
        for project_state in projects.values()
        for request_id in project_state.gates.values()
    }
    try:
        pending_gates = find_pending_bead_gates(_GATE_KINDS)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[bead_task_triage] Failed to scan pending bead gates: {exc}")
        return 0

    canceled = 0
    for gate in pending_gates:
        if gate.producer_chop != "bead_task_triage":
            continue
        if gate.request_id in expected_request_ids:
            continue
        if gate.project in skipped_projects:
            continue
        try:
            was_canceled = _cancel_pending_gate(
                gate.kind,
                gate.request_id,
                reason="gate_no_longer_tracked",
            )
        except Exception as exc:  # noqa: BLE001 - retry on the next tick.
            log.warning(
                f"[bead_task_triage] Failed to cancel untracked gate "
                f"{gate.request_id}: {exc}"
            )
            continue
        canceled += int(was_canceled)
    return canceled


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    projects = _read_state(state_path)
    try:
        inventory = _coerce_project_inventory(_enabled_project_stores(runtime.log))
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(
            f"[bead_task_triage] Failed to load enabled projects: {exc}"
        )
        return _summary(runtime, reason="project_inventory_unavailable")

    gated = 0
    canceled = 0
    skipped = 0
    deferred = 0
    resnoozed = 0
    suppressed_total = 0
    swept_projects = 0
    untracked_canceled = 0
    state_changed = False
    reconciled_projects: set[str] = set()
    skipped_projects = set(inventory.skipped_projects)
    notifications = _NotificationSnoozeIndex()
    try:
        in_flight_launches = active_task_launch_bead_ids()
    except Exception as exc:  # noqa: BLE001 - keep today's triage behavior.
        runtime.log.warning(
            f"[bead_task_triage] Failed to read active task launches: {exc}"
        )
        in_flight_launches = frozenset()

    today = core_time.local_now().date()
    release = sase.__version__
    min_plus_ones = get_task_triage_min_plus_ones()
    for project_name, beads_dir in inventory.stores:
        try:
            gateable = _gateable_beads(beads_dir, today=today, release=release)
        except Exception as exc:  # noqa: BLE001 - one store must not stop the chop.
            skipped_projects.add(project_name)
            runtime.log.warning(
                f"[bead_task_triage] Failed to read gateable beads for "
                f"{_project_display_name(project_name)}: {exc}"
            )
            continue

        suppressed = {
            issue.id
            for issue in gateable
            if task_gate_suppressed(issue, min_plus_ones=min_plus_ones)
        }
        suppressed_total += len(suppressed)
        live_tasks = {
            issue.id: issue for issue in gateable if issue.id not in suppressed
        }

        reconciled_projects.add(project_name)
        project_state = projects.setdefault(project_name, _ProjectState())
        for bead_id, request_id in list(project_state.gates.items()):
            kind = project_state.kinds.get(bead_id, TASK_TRIAGE_KIND)
            try:
                gate_state = _gate_state(kind, request_id)
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to inspect gate {request_id}: {exc}"
                )
                live_tasks.pop(bead_id, None)
                continue

            issue = live_tasks.pop(bead_id, None)
            if issue is not None and gate_state == "pending":
                if bead_id in in_flight_launches:
                    skipped += 1
                    continue
                # A status change outranks the presentation check: the pending
                # gate asks the wrong question entirely, so its fingerprint is
                # not worth comparing.
                wrong_kind = kind != _expected_gate_kind(issue)
                fingerprint = _presentation_fingerprint(issue)
                if (
                    not wrong_kind
                    and project_state.fingerprints.get(bead_id) == fingerprint
                ):
                    skipped += 1
                    try:
                        if kind == BEAD_SNOOZE_KIND and _heal_snoozed_notification(
                            request_id, issue.snooze, notifications
                        ):
                            resnoozed += 1
                    except Exception as exc:  # noqa: BLE001 - retry next tick.
                        runtime.log.warning(
                            f"[bead_task_triage] Failed to re-snooze the "
                            f"notification for gate {request_id}: {exc}"
                        )
                    continue
                try:
                    was_canceled = _cancel_pending_gate(
                        kind,
                        request_id,
                        reason=(
                            "bead_status_changed"
                            if wrong_kind
                            else "task_triage_presentation_changed"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to refresh stale presentation "
                        f"for gate {request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            if issue is None and gate_state == "pending":
                if bead_id in suppressed and bead_id in in_flight_launches:
                    skipped += 1
                    continue
                cancel_reason = (
                    "task_bead_below_plus_one_threshold"
                    if bead_id in suppressed
                    else "task_bead_no_longer_ready"
                )
                try:
                    was_canceled = _cancel_pending_gate(
                        kind, request_id, reason=cancel_reason
                    )
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to cancel stale gate "
                        f"{request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            del project_state.gates[bead_id]
            project_state.fingerprints.pop(bead_id, None)
            project_state.kinds.pop(bead_id, None)
            state_changed = True
            if issue is not None:
                live_tasks[bead_id] = issue

        for bead_id, issue in sorted(live_tasks.items()):
            if bead_id in in_flight_launches:
                deferred += 1
                continue
            generation = project_state.generations.get(bead_id, 0) + 1
            kind = _expected_gate_kind(issue)
            request_id = _request_id(project_name, bead_id, generation, kind)
            try:
                _create_gate(
                    kind,
                    request_id=request_id,
                    bead_id=bead_id,
                    project_name=project_name,
                    issue=issue,
                )
            except Exception as exc:  # noqa: BLE001 - retry deterministically.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to create gate for "
                    f"{project_name}:{bead_id}: {exc}"
                )
                continue
            project_state.gates[bead_id] = request_id
            project_state.generations[bead_id] = generation
            project_state.fingerprints[bead_id] = _presentation_fingerprint(issue)
            project_state.kinds[bead_id] = kind
            gated += 1
            state_changed = True

    if inventory.sweep_allowed:
        (
            inactive_canceled,
            swept_projects,
            inactive_state_changed,
        ) = _sweep_inactive_state_projects(
            projects,
            reconciled_projects=reconciled_projects,
            skipped_projects=skipped_projects,
            log=runtime.log,
        )
        canceled += inactive_canceled
        state_changed = state_changed or inactive_state_changed
        untracked_canceled = _sweep_untracked_produced_gates(
            projects,
            skipped_projects=skipped_projects,
            log=runtime.log,
        )
        canceled += untracked_canceled

    if state_changed:
        try:
            _write_state(state_path, projects)
        except Exception as exc:  # noqa: BLE001 - gate ids make recovery idempotent.
            runtime.log.warning(
                f"[bead_task_triage] Failed to persist reconciliation state: {exc}"
            )

    reason = (
        None
        if (
            gated
            or canceled
            or resnoozed
            or suppressed_total
            or swept_projects
            or untracked_canceled
        )
        else "no_triage_changes"
    )
    return _summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        deferred=deferred,
        resnoozed=resnoozed,
        suppressed=suppressed_total,
        swept_projects=swept_projects,
        untracked_canceled=untracked_canceled,
        reason=reason,
    )


@builtin_chop("bead_task_triage")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("bead_task_triage")


if __name__ == "__main__":
    main()
