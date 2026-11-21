"""Monkeypatchable adapter for the bead-task-triage reconciliation loop."""

from __future__ import annotations

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
from sase.bead.work_liveness import bead_work_in_flight, beads_with_live_agents
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import time as core_time
from sase.notification_gates.durability import file_lock
from sase.notification_gates.models import GateError
from sase.scripts._bead_gate_projects import (
    ProjectInventory,
    coerce_project_inventory,
    enabled_project_stores,
    project_display_name,
)
from sase.scripts._bead_task_triage_gates import (
    GateState,
    NotificationIndex,
    cancel_pending_gate,
    create_gate as create_gate_impl,
    expected_gate_kind,
    gate_notification_id,
    gate_state,
    heal_snoozed_notification,
    presentation_fingerprint,
    reap_settled_bundles,
    request_id,
)
from sase.scripts._bead_task_triage_state import (
    ProjectState,
    gateable_beads,
    read_state,
    write_state,
)
from sase.scripts._bead_task_triage_gate_ops import (
    Superseded,
    count_other_dismissed_pending,
    create_bead_gate,
    keep_tracking,
    log_live_agent_work,
    notification_dismissed,
    pending_refresh_reason,
    retire_predecessor,
    summary,
)
from sase.scripts._bead_task_triage_project_sweeps import (
    sweep_inactive_state_projects,
    sweep_untracked_produced_gates,
)
from sase.scripts._bead_task_triage_tick import reconcile
from sase.scripts._chop_incremental_index import chop_scan_full_walk
from sase.task_type_gate_presentation import (
    resolve_task_type_gate_display,
    task_type_gate_display_payload,
)
from sase.task_types.registry import TaskTypeRegistry, get_task_type_registry

_STATE_FILENAME = "bead_task_triage.json"
_LOCK_FILENAME = "bead_task_triage.lock"
_PRESENTATION_FORMAT_VERSION = 6
_GATE_CONTRACT_VERSION = 2
_GATE_KINDS = (TASK_TRIAGE_KIND, BEAD_SNOOZE_KIND, FLAG_TRIAGE_KIND)
AUTOMATION_OWNED_KINDS = _GATE_KINDS

# These aliases are kept in this implementation module for test doubles and
# direct state inspection. The source names imported from support modules are
# public names; private names are never imported across module boundaries.
_ProjectInventory = ProjectInventory
_ProjectState = ProjectState
_gateable_beads = gateable_beads
_project_display_name = project_display_name
_GateState = GateState
_NotificationIndex = NotificationIndex
_enabled_project_stores_impl = enabled_project_stores
_coerce_project_inventory = coerce_project_inventory
_read_state_impl = read_state
_write_state_impl = write_state
_expected_gate_kind_impl = expected_gate_kind
_request_id_impl = request_id
_presentation_fingerprint_impl = presentation_fingerprint
_gate_state_impl = gate_state
_cancel_pending_gate_impl = cancel_pending_gate
_gate_notification_id_impl = gate_notification_id
_heal_snoozed_notification_impl = heal_snoozed_notification
_create_gate_impl = create_gate_impl
_reap_settled_bundles_impl = reap_settled_bundles


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
    log_live_agent_work(
        log,
        project_name=project_name,
        bead_id=bead_id,
        agent_name=agent_name,
        action=action,
    )


def _pending_refresh_reason(*, worked: bool, wrong_kind: bool) -> str:
    return pending_refresh_reason(worked=worked, wrong_kind=wrong_kind)


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
    return summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        deferred=deferred,
        resnoozed=resnoozed,
        suppressed=suppressed,
        swept_projects=swept_projects,
        untracked_canceled=untracked_canceled,
        reaped_bundles=reaped_bundles,
        other_dismissed_pending=other_dismissed_pending,
        reason=reason,
    )


def _notification_dismissed(
    kind: str, request_id: str, notifications: _NotificationIndex
) -> bool:
    return notification_dismissed(
        kind,
        request_id,
        notifications,
        notification_id_for=_gate_notification_id,
    )


def _count_other_dismissed_pending(notifications: _NotificationIndex) -> int:
    return count_other_dismissed_pending(
        notifications,
        owned_kinds=AUTOMATION_OWNED_KINDS,
        notification_id_for=_gate_notification_id,
    )


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


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    dependencies: dict[str, Any] = {
        "summary": _summary,
        "read_state": _read_state,
        "coerce_project_inventory": _coerce_project_inventory,
        "enabled_project_stores": _enabled_project_stores,
        "notification_index": NotificationIndex,
        "bead_work_in_flight": bead_work_in_flight,
        "beads_with_live_agents": beads_with_live_agents,
        "chop_scan_full_walk": chop_scan_full_walk,
        "core_time": core_time,
        "sase": sase,
        "get_task_triage_min_plus_ones": get_task_triage_min_plus_ones,
        "get_task_type_registry": get_task_type_registry,
        "gateable_beads": _gateable_beads,
        "task_gate_suppressed": task_gate_suppressed,
        "effective_min_plus_ones": effective_min_plus_ones,
        "project_state": _ProjectState,
        "project_display_name": _project_display_name,
        "gate_state": _gate_state,
        "notification_dismissed": _notification_dismissed,
        "owned_kinds": AUTOMATION_OWNED_KINDS,
        "cancel_pending_gate": _cancel_pending_gate,
        "gate_notification_id": _gate_notification_id,
        "expected_gate_kind": _expected_gate_kind,
        "presentation_fingerprint": _presentation_fingerprint,
        "bead_snooze_kind": BEAD_SNOOZE_KIND,
        "task_triage_kind": TASK_TRIAGE_KIND,
        "heal_snoozed_notification": _heal_snoozed_notification,
        "pending_refresh_reason": _pending_refresh_reason,
        "log_live_agent_work": _log_live_agent_work,
        "create_bead_gate": _create_bead_gate,
        "keep_tracking": _keep_tracking,
        "retire_predecessor": _retire_predecessor,
        "sweep_inactive_state_projects": _sweep_inactive_state_projects,
        "sweep_untracked_produced_gates": _sweep_untracked_produced_gates,
        "get_task_triage_settled_bundle_retention_days": (
            get_task_triage_settled_bundle_retention_days
        ),
        "get_task_triage_settled_bundle_reap_cap": get_task_triage_settled_bundle_reap_cap,
        "reap_settled_bundles": _reap_settled_bundles_impl,
        "count_other_dismissed_pending": _count_other_dismissed_pending,
        "write_state": _write_state,
    }
    return reconcile(runtime, state_path, dependencies)


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
    return create_bead_gate(
        log,
        project_state,
        kind=kind,
        project_name=project_name,
        bead_id=bead_id,
        issue=issue,
        notification_id=notification_id,
        request_id_for=_request_id,
        create_gate=_create_gate,
        cancel_conflicting_gate=_cancel_conflicting_gate,
    )


def _retire_predecessor(
    log: ChopLogger, predecessor: Superseded, *, successor_row: str | None
) -> int:
    return retire_predecessor(
        log,
        predecessor,
        successor_row=successor_row,
        cancel_pending_gate=_cancel_pending_gate,
        retire_superseded_gate=_retire_superseded_gate,
    )


def _sweep_inactive_state_projects(
    projects_state: dict[str, _ProjectState],
    *,
    reconciled_projects: set[str],
    skipped_projects: set[str],
    log: ChopLogger,
) -> tuple[int, int, bool]:
    return sweep_inactive_state_projects(
        projects_state,
        reconciled_projects=reconciled_projects,
        skipped_projects=skipped_projects,
        log=log,
        gate_state=_gate_state,
        cancel_pending_gate=_cancel_pending_gate,
    )


def _sweep_untracked_produced_gates(
    projects_state: dict[str, _ProjectState],
    *,
    skipped_projects: set[str],
    log: ChopLogger,
) -> int:
    return sweep_untracked_produced_gates(
        projects_state,
        skipped_projects=skipped_projects,
        log=log,
        gate_kinds=_GATE_KINDS,
        find_pending_gates=find_pending_bead_gates,
        notification_index_factory=_NotificationIndex,
        notification_id_for=_gate_notification_id,
        cancel_pending_gate=_cancel_pending_gate,
        retire_superseded_gate=_retire_superseded_gate,
    )


def _keep_tracking(
    project_state: _ProjectState, bead_id: str, predecessor: Superseded
) -> None:
    keep_tracking(project_state, bead_id, predecessor)


def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


builtin_chop("bead_task_triage")(_run)


def main() -> None:
    run_builtin_chop("bead_task_triage")
