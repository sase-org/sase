#!/usr/bin/env python3
"""Raise and reconcile the one pending gate each live bead may have.

A task bead is either ready — awaiting a ``TaskTriage`` decision — or snoozed,
awaiting a ``BeadSnooze`` wake. A task bead of type ``flag`` whose removal
thresholds have both passed awaits a ``FlagTriage`` decision. All three gate
kinds are reconciled here, in one lane state and under one lock, because
"which gate does this bead have" is a single question: a second chop owning a
second kind could only race this one into giving a bead two pending gates.

A gateable bead is deferred while work is in flight (an active launch proc
**or** a live agent). A pending gate is left in place while the launch proc
is still running — the launch may still fail — and canceled with reason
``bead_work_in_flight`` once a live agent owns the bead.

A pending gate whose rendered presentation drifted is re-presented in place:
its successor generation adopts the pending gate's notification row, and only
then is the superseded gate retired without settling that row. The inbox keeps
one row per bead and gate kind, whose read, dismissed, and snooze state
survive; a row is new and unread only when the gate kind changes or the bead
re-enters a gateable state.

Dismissing a pending triage, snooze, or flag gate's notification cancels it
with reason ``notification_dismissed`` instead of refreshing it. The
cancellation sticks in lane state: no new gate rises for that bead until its
kind changes or it leaves and re-enters a gateable state. Settled bundles of
these kinds older than the configured horizon are reaped under the creation
lock with a per-pass cap; other gate kinds are only counted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sase
from sase.bead.config import (
    get_task_triage_min_plus_ones,
    get_task_triage_settled_bundle_reap_cap,
    get_task_triage_settled_bundle_retention_days,
)
from sase.bead.flag_fields import flag_fields
from sase.bead.flag_gate import FLAG_TRIAGE_KIND, create_flag_triage_gate
from sase.bead.gate_lookup import find_pending_bead_gates
from sase.bead.model import Issue, SnoozeRecord
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND, create_bead_snooze_gate
from sase.bead.task_gate import TASK_TRIAGE_KIND, create_task_triage_gate
from sase.bead.task_triage_policy import effective_min_plus_ones, task_gate_suppressed
from sase.bead.work_liveness import (
    BeadWorkInFlight,
    bead_work_in_flight,
    beads_with_live_agents,
)
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import time as core_time
from sase.notification_gates.durability import file_lock
from sase.notification_gates.models import GateError
from sase.scripts._chop_incremental_index import chop_scan_full_walk
from sase.scripts._bead_task_triage_gates import (
    REQUEST_ID_PREFIXES as _REQUEST_ID_PREFIXES,
    GateState as _GateState,
    NotificationIndex as _NotificationIndex,
    cancel_pending_gate as _cancel_pending_gate_impl,
    create_gate as _create_gate_impl,
    expected_gate_kind as _expected_gate_kind_impl,
    gate_notification_id as _gate_notification_id_impl,
    gate_state as _gate_state_impl,
    heal_snoozed_notification as _heal_snoozed_notification_impl,
    presentation_fingerprint as _presentation_fingerprint_impl,
    reap_settled_bundles as _reap_settled_bundles_impl,
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
from sase.task_type_gate_presentation import (
    resolve_task_type_gate_display,
    task_type_gate_display_payload,
)
from sase.task_types.registry import TaskTypeRegistry, get_task_type_registry

_STATE_FILENAME = "bead_task_triage.json"
_LOCK_FILENAME = "bead_task_triage.lock"

# Bumped whenever a gate preview or notification-note renderer changes shape, so
# the reconciler replaces pending gates still advertising the superseded one.
_PRESENTATION_FORMAT_VERSION = 6

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


def _task_type_display_payload(
    issue: Issue,
    registry: TaskTypeRegistry | None,
) -> dict[str, object] | None:
    """Return the frozen display mapping for a typed bead, or ``None`` if untyped."""
    if not (issue.task_type or "").strip():
        return None
    catalog = get_task_type_registry() if registry is None else registry
    display = resolve_task_type_gate_display(
        issue.task_type,
        issue.task_type_fields,
        registry=catalog,
    )
    if display is None:
        return None
    return task_type_gate_display_payload(display)


def _presentation_fingerprint(
    issue: Issue,
    *,
    registry: TaskTypeRegistry | None = None,
) -> str:
    return _presentation_fingerprint_impl(
        issue,
        format_version=_PRESENTATION_FORMAT_VERSION,
        gate_contract_version=_GATE_CONTRACT_VERSION,
        # Gateable flag beads are always due (see `_gateable_beads`), so this
        # is not a second due-ness comparison -- just threading the one
        # already-known state into the fingerprint.
        flag_due_state="due" if flag_fields(issue) is not None else None,
        task_type_display=_task_type_display_payload(issue, registry),
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


def _retire_superseded_gate(kind: str, request_id: str, *, reason: str) -> bool:
    """Cancel a gate whose notification row a successor gate already adopted."""
    return _cancel_pending_gate_impl(
        kind, request_id, reason=reason, settle_notification=False
    )


def _gate_notification_id(kind: str, request_id: str) -> str | None:
    return _gate_notification_id_impl(kind, request_id)


@dataclass(frozen=True)
class _Superseded:
    """A pending gate whose successor adopts its notification row."""

    kind: str
    request_id: str
    fingerprint: str | None
    notification_id: str


def _heal_snoozed_notification(
    request_id: str,
    snooze: SnoozeRecord | None,
    index: _NotificationIndex,
) -> bool:
    return _heal_snoozed_notification_impl(
        request_id,
        snooze,
        index,
        notification_id_for=_gate_notification_id,
    )


def _log_live_agent_work(
    log: ChopLogger,
    *,
    project_name: str,
    bead_id: str,
    agent_name: str | None,
    action: str,
) -> None:
    owner = agent_name or "unknown"
    log.info(
        f"[bead_task_triage] Live agent {owner} is working "
        f"{project_name}:{bead_id}; {action}"
    )


def _pending_refresh_reason(*, worked: bool, wrong_kind: bool) -> str:
    if worked:
        return "bead_work_in_flight"
    if wrong_kind:
        return "bead_status_changed"
    return "task_triage_presentation_changed"


AUTOMATION_OWNED_KINDS = _GATE_KINDS
"""Gate kinds this chop owns: task triage, bead snooze, and flag triage.

The plan names task triage and bead snooze; flag triage shares the same lane
state and lifecycle, so it follows the same orphan and retention rules. Every
other kind is only counted, never cancelled or reaped here.
"""


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
    reaped_bundles: int = 0,
    other_dismissed_pending: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    counters: dict[str, int] = {
        "gated": gated,
        "canceled": canceled,
        "skipped": skipped,
        "deferred": deferred,
        "resnoozed": resnoozed,
        "suppressed": suppressed,
        "swept_projects": swept_projects,
        "untracked_canceled": untracked_canceled,
    }
    if reaped_bundles:
        counters["reaped_bundles"] = reaped_bundles
    if other_dismissed_pending:
        counters["other_dismissed_pending"] = other_dismissed_pending
    return runtime.emit_summary(
        counters,
        reason=reason,
    )


def _notification_dismissed(
    kind: str, request_id: str, notifications: _NotificationIndex
) -> bool:
    """Return whether the gate's notification row is dismissed.

    A missing notification id or a missing row is not a dismissal: the row
    may have been archived, and an archived dismissal must not cancel a live
    gate. Only an explicit dismissed row counts.
    """
    notification_id = _gate_notification_id(kind, request_id)
    if notification_id is None:
        return False
    try:
        return notifications.is_dismissed(notification_id) is True
    except Exception:
        return False


def _count_other_dismissed_pending(notifications: _NotificationIndex) -> int:
    """Count dismissed-but-pending gates this chop does not own.

    Other gate kinds are only counted: nothing here cancels or reaps them.
    """
    from sase.notification_gates.paths import interaction_requests_dir

    try:
        root = interaction_requests_dir()
        kind_dirs = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return 0
    owned = set(AUTOMATION_OWNED_KINDS)
    count = 0
    for kind_dir in kind_dirs:
        if kind_dir.name.startswith(".") or kind_dir.name in owned:
            continue
        try:
            bundles = sorted(kind_dir.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for bundle_dir in bundles:
            if not bundle_dir.is_dir() or bundle_dir.is_symlink():
                continue
            if (bundle_dir / "response.json").exists() or (
                bundle_dir / "cancellation.json"
            ).exists():
                continue
            try:
                request_id = bundle_dir.name
                notification_id = _gate_notification_id(kind_dir.name, request_id)
            except Exception:
                continue
            if notification_id is None:
                continue
            try:
                if notifications.is_dismissed(notification_id) is True:
                    count += 1
            except Exception:
                continue
    return count


def _create_gate(
    kind: str,
    *,
    request_id: str,
    bead_id: str,
    project_name: str,
    issue: Issue,
    notification_id: str | None = None,
) -> Any:
    return _create_gate_impl(
        kind,
        request_id=request_id,
        bead_id=bead_id,
        project_name=project_name,
        issue=issue,
        task_gate_factory=create_task_triage_gate,
        flag_gate_factory=create_flag_triage_gate,
        snooze_gate_factory=create_bead_snooze_gate,
        notification_id=notification_id,
    )


def _cancel_conflicting_gate(
    kind: str, request_id: str, *, adopted_notification_id: str | None
) -> None:
    """Retire a gate whose request id a different specification already holds.

    A conflicting gate that already adopted the row this re-presentation
    carries (a pass that crashed after creating it) is retired without
    settling that row, so the retry can adopt it again.
    """
    if (
        adopted_notification_id is not None
        and _gate_notification_id(kind, request_id) == adopted_notification_id
    ):
        _retire_superseded_gate(kind, request_id, reason="request_id_conflict")
        return
    _cancel_pending_gate(kind, request_id, reason="request_id_conflict")


def _create_bead_gate(
    log: ChopLogger,
    project_state: _ProjectState,
    *,
    kind: str,
    project_name: str,
    bead_id: str,
    issue: Issue,
    notification_id: str | None,
) -> tuple[str, int, Any] | None:
    """Create a bead's next-generation gate; ``None`` when none exists yet.

    A ``request_id_conflict`` retires the conflicting gate, records a fresh
    generation that survives even if the bounded retry fails, and retries.
    """
    generation = project_state.generations.get(bead_id, 0) + 1
    request_id = _request_id(project_name, bead_id, generation, kind)
    try:
        result = _create_gate(
            kind,
            request_id=request_id,
            bead_id=bead_id,
            project_name=project_name,
            issue=issue,
            notification_id=notification_id,
        )
    except GateError as exc:
        if exc.code != "request_id_conflict":
            log.warning(
                f"[bead_task_triage] Failed to create gate for "
                f"{project_name}:{bead_id}: {exc}"
            )
            return None

        # A conflicting id belongs to an earlier gate specification.
        # Retire it when it is still pending, then record a fresh
        # generation that survives even if the bounded retry fails.
        try:
            _cancel_conflicting_gate(
                kind, request_id, adopted_notification_id=notification_id
            )
        except GateError as cancel_exc:
            if cancel_exc.code not in {
                "already_answered",
                "already_canceled",
                "not_pending",
            }:
                log.warning(
                    f"[bead_task_triage] Failed to cancel conflicting "
                    f"gate {request_id}: {cancel_exc}"
                )
        except Exception as cancel_exc:  # noqa: BLE001 - keep generation durable.
            log.warning(
                f"[bead_task_triage] Failed to cancel conflicting "
                f"gate {request_id}: {cancel_exc}"
            )

        retry_generation = generation + 1
        retry_request_id = _request_id(project_name, bead_id, retry_generation, kind)
        project_state.generations[bead_id] = retry_generation
        log.warning(
            f"[bead_task_triage] request_id_conflict for {request_id}; "
            f"retrying with {retry_request_id}"
        )
        try:
            result = _create_gate(
                kind,
                request_id=retry_request_id,
                bead_id=bead_id,
                project_name=project_name,
                issue=issue,
                notification_id=notification_id,
            )
        except Exception as retry_exc:  # noqa: BLE001 - retry next pass.
            log.warning(
                f"[bead_task_triage] Failed to create gate for "
                f"{project_name}:{bead_id}: {retry_exc}"
            )
            return None
        return retry_request_id, retry_generation, result
    except Exception as exc:  # noqa: BLE001 - retry deterministically.
        log.warning(
            f"[bead_task_triage] Failed to create gate for "
            f"{project_name}:{bead_id}: {exc}"
        )
        return None
    return request_id, generation, result


def _retire_predecessor(
    log: ChopLogger, predecessor: _Superseded, *, successor_row: str | None
) -> int:
    """Retire the gate a successor re-presented; 1 when this pass canceled it.

    When the successor adopted the predecessor's row, the cancellation leaves
    the row to the successor; otherwise the predecessor settles its own row.
    A failure leaves the predecessor untracked, so the untracked sweep
    retires it on a later pass.
    """
    try:
        if successor_row == predecessor.notification_id:
            was_canceled = _retire_superseded_gate(
                predecessor.kind,
                predecessor.request_id,
                reason="task_triage_presentation_changed",
            )
        else:
            was_canceled = _cancel_pending_gate(
                predecessor.kind,
                predecessor.request_id,
                reason="task_triage_presentation_changed",
            )
    except Exception as exc:  # noqa: BLE001 - the untracked sweep retries it.
        log.warning(
            f"[bead_task_triage] Failed to retire superseded gate "
            f"{predecessor.request_id}: {exc}"
        )
        return 0
    return int(was_canceled)


def _keep_tracking(
    project_state: _ProjectState, bead_id: str, predecessor: _Superseded
) -> None:
    """Re-track a superseded gate whose successor could not be created."""
    project_state.gates[bead_id] = predecessor.request_id
    project_state.kinds[bead_id] = predecessor.kind
    if predecessor.fingerprint is not None:
        project_state.fingerprints[bead_id] = predecessor.fingerprint


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
    notifications = _NotificationIndex()
    for gate in pending_gates:
        if gate.producer_chop != "bead_task_triage":
            continue
        if gate.request_id in expected_request_ids:
            continue
        if gate.project in skipped_projects:
            continue
        try:
            row = _gate_notification_id(gate.kind, gate.request_id)
            presented = None if row is None else notifications.presented_request_id(row)
            # A superseded gate whose retirement failed: its row now presents
            # the successor, which must keep it.
            cancel = (
                _retire_superseded_gate
                if presented is not None and presented != gate.request_id
                else _cancel_pending_gate
            )
            was_canceled = cancel(
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
    notifications = _NotificationIndex()
    work: BeadWorkInFlight = bead_work_in_flight(
        runtime.log.warning,
        live_agents=lambda: beads_with_live_agents(use_index=not chop_scan_full_walk()),
    )

    today = core_time.local_now().date()
    release = sase.__version__
    min_plus_ones = get_task_triage_min_plus_ones()
    task_type_registry = get_task_type_registry()
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
            if task_gate_suppressed(
                issue,
                min_plus_ones=effective_min_plus_ones(
                    issue,
                    registry=task_type_registry,
                    global_default=min_plus_ones,
                ),
            )
        }
        suppressed_total += len(suppressed)
        live_tasks = {
            issue.id: issue for issue in gateable if issue.id not in suppressed
        }

        reconciled_projects.add(project_name)
        project_state = projects.setdefault(project_name, _ProjectState())
        gateable_ids = {issue.id for issue in gateable}
        for suppressed_bead in list(project_state.dismissed):
            if suppressed_bead not in gateable_ids:
                del project_state.dismissed[suppressed_bead]
                state_changed = True
        superseded: dict[str, _Superseded] = {}
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
                if kind in AUTOMATION_OWNED_KINDS and _notification_dismissed(
                    kind, request_id, notifications
                ):
                    try:
                        was_canceled = _cancel_pending_gate(
                            kind, request_id, reason="notification_dismissed"
                        )
                    except Exception as exc:  # noqa: BLE001 - retry next tick.
                        runtime.log.warning(
                            f"[bead_task_triage] Failed to cancel dismissed gate "
                            f"{request_id}: {exc}"
                        )
                        live_tasks[bead_id] = issue
                        continue
                    canceled += int(was_canceled)
                    del project_state.gates[bead_id]
                    project_state.fingerprints.pop(bead_id, None)
                    project_state.kinds.pop(bead_id, None)
                    if project_state.dismissed.get(bead_id) != kind:
                        project_state.dismissed[bead_id] = kind
                        state_changed = True
                    # A dismissal-cancel never recreates on this pass: the next
                    # pass sees the sticky suppression and keeps the row gone.
                    # Dismissing a notification never undismisses it.
                    notifications.forget(_gate_notification_id(kind, request_id) or "")
                    state_changed = True
                    continue
                if work.is_launching(bead_id):
                    skipped += 1
                    continue
                # A live agent outranks the fingerprint shortcut: the pending
                # ask is already stale for the whole remaining run. A status
                # change still outranks a mere presentation drift.
                worked = work.is_worked(project_name, bead_id)
                wrong_kind = kind != _expected_gate_kind(issue)
                fingerprint = _presentation_fingerprint(
                    issue, registry=task_type_registry
                )
                if (
                    not worked
                    and not wrong_kind
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
                adopt_row = (
                    None
                    if worked or wrong_kind
                    else _gate_notification_id(kind, request_id)
                )
                if adopt_row is not None:
                    # Re-present in place: the successor adopts this row
                    # below, and only then is this gate retired.
                    superseded[bead_id] = _Superseded(
                        kind=kind,
                        request_id=request_id,
                        fingerprint=project_state.fingerprints.get(bead_id),
                        notification_id=adopt_row,
                    )
                else:
                    try:
                        was_canceled = _cancel_pending_gate(
                            kind,
                            request_id,
                            reason=_pending_refresh_reason(
                                worked=worked, wrong_kind=wrong_kind
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001 - retry next tick.
                        runtime.log.warning(
                            f"[bead_task_triage] Failed to refresh stale "
                            f"presentation for gate {request_id}: {exc}"
                        )
                        continue
                    canceled += int(was_canceled)
                if worked:
                    _log_live_agent_work(
                        runtime.log,
                        project_name=project_name,
                        bead_id=bead_id,
                        agent_name=work.agent_name(project_name, bead_id),
                        action="canceling pending gate",
                    )

            if issue is None and gate_state == "pending":
                if bead_id in project_state.dismissed:
                    del project_state.dismissed[bead_id]
                    state_changed = True
                if bead_id in suppressed and work.is_launching(bead_id):
                    skipped += 1
                    continue
                if kind in AUTOMATION_OWNED_KINDS and _notification_dismissed(
                    kind, request_id, notifications
                ):
                    cancel_reason = "notification_dismissed"
                else:
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
                try:
                    notifications.forget(_gate_notification_id(kind, request_id) or "")
                except Exception:
                    pass

            del project_state.gates[bead_id]
            project_state.fingerprints.pop(bead_id, None)
            project_state.kinds.pop(bead_id, None)
            state_changed = True
            if issue is not None:
                live_tasks[bead_id] = issue

        for bead_id, issue in sorted(live_tasks.items()):
            predecessor = superseded.get(bead_id)
            if work.covers(project_name, bead_id):
                if work.is_worked(project_name, bead_id):
                    _log_live_agent_work(
                        runtime.log,
                        project_name=project_name,
                        bead_id=bead_id,
                        agent_name=work.agent_name(project_name, bead_id),
                        action="deferring new gate",
                    )
                deferred += 1
                continue
            kind = _expected_gate_kind(issue)
            suppressed_kind = project_state.dismissed.get(bead_id)
            if suppressed_kind is not None:
                if suppressed_kind == kind:
                    skipped += 1
                    continue
                del project_state.dismissed[bead_id]
                state_changed = True
            generations_before = project_state.generations.get(bead_id)
            created = _create_bead_gate(
                runtime.log,
                project_state,
                kind=kind,
                project_name=project_name,
                bead_id=bead_id,
                issue=issue,
                notification_id=(
                    None if predecessor is None else predecessor.notification_id
                ),
            )
            if project_state.generations.get(bead_id) != generations_before:
                state_changed = True
            if created is None:
                if predecessor is not None:
                    _keep_tracking(project_state, bead_id, predecessor)
                continue
            request_id, generation, result = created
            project_state.gates[bead_id] = request_id
            project_state.generations[bead_id] = generation
            project_state.fingerprints[bead_id] = _presentation_fingerprint(
                issue, registry=task_type_registry
            )
            project_state.kinds[bead_id] = kind
            if bead_id in project_state.dismissed:
                del project_state.dismissed[bead_id]
            gated += 1
            state_changed = True
            if predecessor is not None:
                canceled += _retire_predecessor(
                    runtime.log,
                    predecessor,
                    successor_row=getattr(result, "notification_id", None),
                )

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

    try:
        retention_days = get_task_triage_settled_bundle_retention_days()
    except Exception:
        retention_days = 30
    try:
        reap_cap = get_task_triage_settled_bundle_reap_cap()
    except Exception:
        reap_cap = 100
    try:
        reaped_bundles, reap_capped = _reap_settled_bundles_impl(
            AUTOMATION_OWNED_KINDS,
            retention_days=retention_days,
            cap=reap_cap,
        )
    except Exception as exc:  # noqa: BLE001 - retention must not fail triage.
        runtime.log.warning(f"[bead_task_triage] Failed to reap settled bundles: {exc}")
        reaped_bundles = 0
        reap_capped = False
    if reap_capped:
        runtime.log.info(
            f"[bead_task_triage] Settled-bundle reap hit its per-pass cap "
            f"({reap_cap}); the remainder waits for the next pass."
        )
    try:
        other_dismissed_pending = _count_other_dismissed_pending(notifications)
    except Exception:
        other_dismissed_pending = 0

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
            or reaped_bundles
            or other_dismissed_pending
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
        reaped_bundles=reaped_bundles,
        other_dismissed_pending=other_dismissed_pending,
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
