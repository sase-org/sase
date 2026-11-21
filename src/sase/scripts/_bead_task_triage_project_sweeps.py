"""Project state cleanup operations for bead-task-triage."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.bead.task_gate import TASK_TRIAGE_KIND
from sase.chops.sdk import ChopLogger
from sase.scripts._bead_gate_projects import project_display_name
from sase.scripts._bead_task_triage_gates import NotificationIndex
from sase.scripts._bead_task_triage_state import ProjectState


def sweep_inactive_state_projects(
    projects: dict[str, ProjectState],
    *,
    reconciled_projects: set[str],
    skipped_projects: set[str],
    log: ChopLogger,
    gate_state: Callable[[str, str], str],
    cancel_pending_gate: Callable[..., bool],
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
                state = gate_state(kind, request_id)
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                log.warning(
                    f"[bead_task_triage] Failed to inspect inactive-project "
                    f"gate {request_id} for "
                    f"{project_display_name(project_name)}: {exc}"
                )
                failed = True
                continue
            if state != "pending":
                continue
            try:
                was_canceled = cancel_pending_gate(
                    kind,
                    request_id,
                    reason="project_no_longer_enabled",
                )
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                log.warning(
                    f"[bead_task_triage] Failed to cancel inactive-project "
                    f"gate {request_id} for "
                    f"{project_display_name(project_name)}: {exc}"
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


def sweep_untracked_produced_gates(
    projects: dict[str, ProjectState],
    *,
    skipped_projects: set[str],
    log: ChopLogger,
    gate_kinds: tuple[str, ...],
    find_pending_gates: Callable[[tuple[str, ...]], Any],
    notification_index_factory: Callable[[], NotificationIndex],
    notification_id_for: Callable[[str, str], str | None],
    cancel_pending_gate: Callable[..., bool],
    retire_superseded_gate: Callable[..., bool],
) -> int:
    """Cancel pending gates this chop produced but no longer records in state."""
    expected_request_ids = {
        request_id
        for project_state in projects.values()
        for request_id in project_state.gates.values()
    }
    try:
        pending_gates = find_pending_gates(gate_kinds)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        log.warning(f"[bead_task_triage] Failed to scan pending bead gates: {exc}")
        return 0

    canceled = 0
    notifications = notification_index_factory()
    for gate in pending_gates:
        if gate.producer_chop != "bead_task_triage":
            continue
        if gate.request_id in expected_request_ids:
            continue
        if gate.project in skipped_projects:
            continue
        try:
            row = notification_id_for(gate.kind, gate.request_id)
            presented = None if row is None else notifications.presented_request_id(row)
            # A superseded gate whose retirement failed: its row now presents
            # the successor, which must keep it.
            cancel = (
                retire_superseded_gate
                if presented is not None and presented != gate.request_id
                else cancel_pending_gate
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
