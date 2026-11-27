"""Per-project jobs for the ``artifact_link_backfill`` chop.

Runs one enabled project's touch-index refresh, publication retry sweep,
resumable derivation sweep, read-outbox drain, and reconcile/repair pass
under the chop's budgets, accumulating counters into ``BackfillTotals``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sase.chops.builtin import BuiltinChopRuntime
from sase.scripts._artifact_link_backfill_schedule import (
    BackfillSchedule,
    write_backfill_schedule,
)
from sase.scripts._artifact_link_backfill_state import write_sweep_state
from sase.sdd._artifact_link_incremental import document_sweep_fingerprint
from sase.sdd._artifact_link_outbox_drain_support import (
    AgentTerminalTimes,
    render_drain_phase_seconds,
)
from sase.sdd._artifact_link_publication_retry import (
    ArtifactLinkPublicationRetryDetail,
    sweep_artifact_link_publication_retries,
)
from sase.sdd.artifact_link_backfill import (
    reconcile_and_repair_artifact_links,
    run_artifact_link_backfill_batch,
)
from sase.sdd.artifact_link_outbox import drain_artifact_link_outbox
from sase.sdd.artifact_link_store import (
    machine_document_sidecar_roots,
    resolve_machine_artifact_link_store,
)

CHOP_NAME = "artifact_link_backfill"
_SWEEP_BATCH_SIZE = 500
_RECONCILE_CUT_SHORT_DIAGNOSTIC = "reconcile deadline expired"
_RECONCILE_ESTIMATE_MARGIN = 1.5


@dataclass
class BackfillTotals:
    projects: int = 0
    touch_index_refreshed: int = 0
    touch_index_reduced_streams: int = 0
    failed_projects: int = 0
    sweep_scanned: int = 0
    sweep_persisted: int = 0
    sweep_remaining: int = 0
    sweep_skipped: int = 0
    outbox_drained: int = 0
    outbox_dropped: int = 0
    publication_attempted: int = 0
    publication_published: int = 0
    publication_deferred: int = 0
    publication_failed: int = 0
    publication_aged: int = 0
    publication_discovered: int = 0
    publication_cleared: int = 0
    reconciled: int = 0
    reconcile_skipped: int = 0
    projection_refreshed: int = 0
    rename_scan_skipped: int = 0
    repaired_renames: int = 0
    deferred_projects: int = 0
    stale_checked_projects: int = 0
    bead_projection_failed: int = 0
    parked_new: int = 0
    parked_total: int = 0
    transient: int = 0
    warnings: list[str] = field(default_factory=list)


def _log_project_done(
    runtime: BuiltinChopRuntime,
    project_key: str,
    elapsed: dict[str, float],
    started: float,
) -> None:
    jobs = ", ".join(f"{name}={value:.2f}s" for name, value in elapsed.items())
    total = time.monotonic() - started
    runtime.log.info(f"[{CHOP_NAME}] {project_key}: done in {total:.2f}s ({jobs})")


def _log_project_stage(
    runtime: BuiltinChopRuntime, project_key: str, stage: str
) -> None:
    runtime.log.info(f"[{CHOP_NAME}] {project_key}: {stage}")


def persist_backfill_schedule(
    path: Path, schedule: BackfillSchedule, totals: BackfillTotals
) -> None:
    try:
        write_backfill_schedule(path, schedule)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        totals.warnings.append(f"failed to persist backfill schedule: {exc}")


def _sweep_phase_line(project_key: str, report: object) -> str:
    rendered = " ".join(
        f"{name}={value:.2f}s"
        for name, value in (getattr(report, "phase_seconds", ()) or ())
    )
    return f"[{CHOP_NAME}] {project_key}: sweep phases: {rendered}"


def _drain_phase_line(
    project_key: str, report: object, *, catalog_built_before: bool
) -> str:
    """Render one drain's per-phase timings for the chop log.

    ``catalog`` reads ``skipped`` when the drain never consulted the agent
    catalog and ``shared`` when an earlier project in this run built it.
    """

    rendered = render_drain_phase_seconds(
        getattr(report, "phase_seconds", ()) or (),
        catalog_shared=catalog_built_before,
    )
    return f"[{CHOP_NAME}] {project_key}: drain phases: {rendered}"


def _publication_detail_line(detail: ArtifactLinkPublicationRetryDetail) -> str:
    parts = [
        f"{detail.project_key}/{detail.role}: publication {detail.status}",
        f"age={detail.age_seconds:.0f}s",
    ]
    if detail.last_error:
        parts.append(f"last_error={detail.last_error}")
    if detail.next_due_at is not None:
        parts.append(f"next_due_at={detail.next_due_at:.0f}")
    if detail.log_path is not None:
        parts.append(f"log={detail.log_path}")
    if detail.diagnostic:
        parts.append(f"diagnostic={detail.diagnostic}")
    return "; ".join(parts)


def _refresh_touch_index_for_project(
    project_key: str,
    workspace_dir: str,
    *,
    totals: BackfillTotals,
    runtime: BuiltinChopRuntime,
) -> None:
    """Refresh one project's agent/bead touch index, best-effort.

    The refresh is incremental and skips its write when nothing changed, so
    the steady-state cost is one stat pass over the streams. Any failure is
    a logged warning, never a failed project: the next mutation, sync, or
    tick converges the store instead.
    """
    try:
        from sase.bead.cli_location import find_beads_location
        from sase.core.bead_touch_index_facade import (
            BeadTouchRefresh,
            refresh_touch_index_best_effort,
        )

        root, beads_dirname = find_beads_location(cwd=Path(workspace_dir))
        beads_dir = root / beads_dirname
        if not beads_dir.is_dir():
            return
        report: BeadTouchRefresh | None = refresh_touch_index_best_effort(
            beads_dir, project=project_key
        )
    except Exception as exc:  # noqa: BLE001 - one broken project cannot stall the rest.
        totals.warnings.append(f"{project_key}: touch-index refresh failed: {exc}")
        return
    if report is None:
        return
    totals.touch_index_refreshed += 1
    totals.touch_index_reduced_streams += len(report.reduced_streams)
    if report.reduced_streams:
        runtime.log.info(
            f"[{CHOP_NAME}] {project_key}: touch index re-reduced "
            f"{len(report.reduced_streams)} stream(s)"
        )


def run_project(
    project_key: str,
    workspace_dir: str,
    *,
    swept: dict[str, list[str]],
    totals: BackfillTotals,
    deadline: float,
    chop_deadline: float,
    state_path: Path,
    schedule_path: Path,
    runtime: BuiltinChopRuntime,
    terminal_times: AgentTerminalTimes,
    schedule: BackfillSchedule,
    first_project: bool,
) -> bool:
    """Run one project's jobs; return whether budget deferred any of its work.

    The sweep-backlog early return is not a deferral: the sweep simply has
    more documents left for later ticks.
    """

    started = time.monotonic()
    runtime.log.info(f"[{CHOP_NAME}] {project_key}: starting")
    elapsed: dict[str, float] = {}

    _log_project_stage(runtime, project_key, "touch_index")
    touch_index_started = time.monotonic()
    _refresh_touch_index_for_project(
        project_key, workspace_dir, totals=totals, runtime=runtime
    )
    elapsed["touch_index"] = time.monotonic() - touch_index_started

    _log_project_stage(runtime, project_key, "publication_retry")
    publication_started = time.monotonic()
    roots, root_diagnostics = machine_document_sidecar_roots(
        project_key, Path(workspace_dir), deadline=chop_deadline
    )
    totals.warnings.extend(f"{project_key}: {item}" for item in root_diagnostics)
    if roots and time.monotonic() < chop_deadline:
        retry_report = sweep_artifact_link_publication_retries(
            roots,
            deadline=chop_deadline,
            worker_lock_wait=5.0,
        )
        totals.publication_attempted += retry_report.attempted
        totals.publication_published += retry_report.published
        totals.publication_deferred += retry_report.deferred
        totals.publication_failed += retry_report.failed
        totals.publication_aged += retry_report.aged
        totals.publication_discovered += retry_report.discovered
        totals.publication_cleared += retry_report.cleared
        totals.warnings.extend(retry_report.diagnostics)
        for detail in retry_report.details:
            if detail.status in {"failed", "deferred"} or detail.last_error:
                totals.warnings.append(_publication_detail_line(detail))
    elapsed["publication_retry"] = time.monotonic() - publication_started

    _log_project_stage(runtime, project_key, "store_resolution")
    resolve_started = time.monotonic()
    try:
        store = resolve_machine_artifact_link_store(
            project_key, Path(workspace_dir), deadline=chop_deadline
        )
    except Exception as exc:  # noqa: BLE001 - one broken project cannot stall the rest.
        totals.failed_projects += 1
        totals.warnings.append(f"{project_key}: could not resolve link store: {exc}")
        elapsed["store_resolution"] = time.monotonic() - resolve_started
        _log_project_done(runtime, project_key, elapsed, started)
        return False
    elapsed["store_resolution"] = time.monotonic() - resolve_started

    priority_first = first_project and schedule.has_reconcile_priority(project_key)
    sweep_fingerprint = document_sweep_fingerprint(store)
    if priority_first:
        _log_project_stage(runtime, project_key, "sweep skipped (reconcile priority)")
    elif time.monotonic() < deadline and schedule.sweep_skippable(
        project_key, sweep_fingerprint, now=time.time()
    ):
        totals.sweep_skipped += 1
    elif time.monotonic() < deadline:
        _log_project_stage(runtime, project_key, "sweep")
        sweep_started = time.monotonic()
        already_swept = frozenset(swept.get(project_key, ()))
        report, updated_swept = run_artifact_link_backfill_batch(
            store,
            already_swept=already_swept,
            batch_size=_SWEEP_BATCH_SIZE,
            deadline=deadline,
            persist_deadline=chop_deadline,
        )
        elapsed["sweep"] = time.monotonic() - sweep_started
        if report.phase_seconds:
            runtime.log.info(_sweep_phase_line(project_key, report))
        schedule.record_sweep(
            project_key,
            sweep_fingerprint,
            complete=report.remaining == 0 and not report.errors,
            now=time.time(),
        )
        swept[project_key] = sorted(updated_swept)
        totals.sweep_scanned += report.scanned
        totals.sweep_persisted += report.persisted
        totals.sweep_remaining += report.remaining
        totals.warnings.extend(f"{project_key}: {error}" for error in report.errors)
        try:
            write_sweep_state(state_path, swept)
        except Exception as exc:  # noqa: BLE001 - retry on the next tick.
            totals.warnings.append(f"failed to persist sweep checkpoint: {exc}")
        persist_backfill_schedule(schedule_path, schedule, totals)
        if report.remaining and time.monotonic() >= deadline:
            totals.warnings.append(
                f"{project_key}: deferred outbox/reconcile after sweep budget"
            )
            totals.projects += 1
            _log_project_done(runtime, project_key, elapsed, started)
            return False

    if time.monotonic() >= chop_deadline:
        totals.deferred_projects += 1
        totals.warnings.append(
            f"{project_key}: deferred outbox drain and reconcile/repair past job budget"
        )
        _log_project_done(runtime, project_key, elapsed, started)
        return True

    _log_project_stage(runtime, project_key, "drain")
    drain_started = time.monotonic()
    drain_deferred = False
    stale_deferred = False
    stale_due = schedule.stale_drop_due(project_key, now=time.time())
    catalog_built_before = terminal_times.built
    try:
        outbox_report = drain_artifact_link_outbox(
            store=store,
            deadline=chop_deadline,
            drop_stale_terminal=stale_due,
            terminal_times=terminal_times,
        )
        runtime.log.info(
            _drain_phase_line(
                project_key,
                outbox_report,
                catalog_built_before=catalog_built_before,
            )
        )
        if bool(getattr(outbox_report, "stale_checked", False)):
            schedule.record_stale_checked(project_key, now=time.time())
            totals.stale_checked_projects += 1
        elif stale_due:
            stale_deferred = True
        totals.outbox_drained += outbox_report.drained
        totals.outbox_dropped += outbox_report.dropped
        totals.parked_new += int(getattr(outbox_report, "parked_new", 0) or 0)
        totals.parked_total += int(getattr(outbox_report, "parked_total", 0) or 0)
        totals.transient += int(getattr(outbox_report, "transient", 0) or 0)
        totals.bead_projection_failed += int(
            getattr(outbox_report, "bead_projection_failed", 0) or 0
        )
        for detail in getattr(outbox_report, "parked_details", ())[:5]:
            reasons = "; ".join(getattr(detail, "reasons", ()) or ())
            runtime.log.info(
                f"[{CHOP_NAME}] {project_key}: parked {detail.operation_id}"
                + (f": {reasons}" if reasons else "")
            )
        totals.warnings.extend(
            f"{project_key}: {item}"
            for item in getattr(outbox_report, "skip_diagnostics", ())
        )
        drain_deferred = bool(getattr(outbox_report, "deferred", False))
    except Exception as exc:  # noqa: BLE001 - continue with the other jobs.
        totals.warnings.append(f"{project_key}: outbox drain failed: {exc}")
    elapsed["drain"] = time.monotonic() - drain_started

    if drain_deferred or time.monotonic() >= chop_deadline:
        totals.deferred_projects += 1
        if not drain_deferred:
            totals.warnings.append(
                f"{project_key}: deferred reconcile/repair past job budget"
            )
        totals.projects += 1
        _log_project_done(runtime, project_key, elapsed, started)
        return True

    memo = schedule.reconcile_memo(project_key)
    estimate = schedule.reconcile_estimate(project_key)
    remaining = chop_deadline - time.monotonic()
    # A memo that can still vouch for a skip makes the cheap path likely; a
    # full reconcile that does run past the deadline defers as before.
    skip_plausible = memo.input_fingerprint is not None and not (
        memo.full_pass_due(now=time.time())
    )
    needed = estimate * _RECONCILE_ESTIMATE_MARGIN
    if not skip_plausible and remaining < needed and not priority_first:
        schedule.mark_reconcile_priority(project_key)
        totals.deferred_projects += 1
        totals.warnings.append(
            f"{project_key}: deferred reconcile/repair: "
            f"needs ~{estimate:.0f}s, {remaining:.0f}s left"
        )
        totals.projects += 1
        _log_project_done(runtime, project_key, elapsed, started)
        return True

    _log_project_stage(runtime, project_key, "reconcile")
    reconcile_started = time.monotonic()
    reconcile_deferred = False
    full_reconcile = not skip_plausible
    if full_reconcile:
        schedule.mark_reconcile_started(project_key, now=time.time())
        persist_backfill_schedule(schedule_path, schedule, totals)
    try:
        reconcile_report = reconcile_and_repair_artifact_links(
            store,
            deadline=chop_deadline,
            progress=lambda stage: _log_project_stage(
                runtime, project_key, f"reconcile/{stage}"
            ),
            memo=memo,
            now=time.time(),
        )
        reconcile_skipped = bool(getattr(reconcile_report, "reconcile_skipped", False))
        totals.reconciled += 1
        totals.reconcile_skipped += int(reconcile_skipped)
        totals.projection_refreshed += int(
            bool(getattr(reconcile_report, "projection_changed", False))
        )
        totals.rename_scan_skipped += int(
            bool(getattr(reconcile_report, "rename_scan_skipped", False))
        )
        totals.repaired_renames += reconcile_report.repaired_renames
        totals.warnings.extend(
            f"{project_key}: {item}" for item in reconcile_report.skip_diagnostics
        )
        if reconcile_report.deferred_refs > 0:
            totals.warnings.append(
                f"{project_key}: deferred {reconcile_report.deferred_refs} "
                "dangling-ref repairs past job budget"
            )
        reconcile_deferred = reconcile_report.deferred_refs > 0 or any(
            _RECONCILE_CUT_SHORT_DIAGNOSTIC in str(item)
            for item in reconcile_report.skip_diagnostics
        )
        if reconcile_deferred:
            schedule.mark_reconcile_priority(project_key)
        else:
            schedule.clear_reconcile_priority(project_key)
            if not reconcile_skipped:
                # The estimate gates a full reconcile, so a cheap skipped pass
                # must not talk it down.
                schedule.record_reconcile(
                    project_key, time.monotonic() - reconcile_started
                )
    except Exception as exc:  # noqa: BLE001 - continue with the other projects.
        schedule.mark_reconcile_priority(project_key)
        totals.warnings.append(f"{project_key}: reconcile/repair failed: {exc}")
    finally:
        if full_reconcile:
            schedule.clear_reconcile_started(project_key)
            persist_backfill_schedule(schedule_path, schedule, totals)
    elapsed["reconcile_repair"] = time.monotonic() - reconcile_started

    totals.projects += 1
    _log_project_done(runtime, project_key, elapsed, started)
    return stale_deferred or reconcile_deferred
