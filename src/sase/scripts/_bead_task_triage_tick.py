"""Single-pass reconciliation loop for the bead-task-triage chop."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.bead.work_liveness import BeadWorkInFlight
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopResultBuilder
from sase.scripts._bead_task_triage_gate_ops import Superseded


def reconcile(
    runtime: BuiltinChopRuntime,
    state_path: Path,
    dependencies: dict[str, Any],
) -> ChopResultBuilder:
    _summary = dependencies["summary"]
    _read_state = dependencies["read_state"]
    _coerce_project_inventory = dependencies["coerce_project_inventory"]
    _enabled_project_stores = dependencies["enabled_project_stores"]
    _NotificationIndex = dependencies["notification_index"]
    bead_work_in_flight = dependencies["bead_work_in_flight"]
    beads_with_live_agents = dependencies["beads_with_live_agents"]
    chop_scan_full_walk = dependencies["chop_scan_full_walk"]
    core_time = dependencies["core_time"]
    sase = dependencies["sase"]
    get_task_triage_min_plus_ones = dependencies["get_task_triage_min_plus_ones"]
    get_task_type_registry = dependencies["get_task_type_registry"]
    _gateable_beads = dependencies["gateable_beads"]
    task_gate_suppressed = dependencies["task_gate_suppressed"]
    effective_min_plus_ones = dependencies["effective_min_plus_ones"]
    _ProjectState = dependencies["project_state"]
    _project_display_name = dependencies["project_display_name"]
    _gate_state = dependencies["gate_state"]
    _notification_dismissed = dependencies["notification_dismissed"]
    AUTOMATION_OWNED_KINDS = dependencies["owned_kinds"]
    _cancel_pending_gate = dependencies["cancel_pending_gate"]
    _gate_notification_id = dependencies["gate_notification_id"]
    _expected_gate_kind = dependencies["expected_gate_kind"]
    _presentation_fingerprint = dependencies["presentation_fingerprint"]
    BEAD_SNOOZE_KIND = dependencies["bead_snooze_kind"]
    TASK_TRIAGE_KIND = dependencies["task_triage_kind"]
    _heal_snoozed_notification = dependencies["heal_snoozed_notification"]
    _pending_refresh_reason = dependencies["pending_refresh_reason"]
    _log_live_agent_work = dependencies["log_live_agent_work"]
    _create_bead_gate = dependencies["create_bead_gate"]
    _keep_tracking = dependencies["keep_tracking"]
    _retire_predecessor = dependencies["retire_predecessor"]
    _sweep_inactive_state_projects = dependencies["sweep_inactive_state_projects"]
    _sweep_untracked_produced_gates = dependencies["sweep_untracked_produced_gates"]
    get_task_triage_settled_bundle_retention_days = dependencies[
        "get_task_triage_settled_bundle_retention_days"
    ]
    get_task_triage_settled_bundle_reap_cap = dependencies[
        "get_task_triage_settled_bundle_reap_cap"
    ]
    _reap_settled_bundles_impl = dependencies["reap_settled_bundles"]
    _count_other_dismissed_pending = dependencies["count_other_dismissed_pending"]
    _write_state = dependencies["write_state"]
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
        superseded: dict[str, Superseded] = {}
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
                    superseded[bead_id] = Superseded(
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
