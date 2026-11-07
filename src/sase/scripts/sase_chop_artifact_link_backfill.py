#!/usr/bin/env python3
"""Retroactive artifact-link derivation, outbox drain, and repair sweep.

An hourly housekeeping chop, since it may scan substantial local state. It
owns five bounded jobs per enabled project, each reporting what it did:

1. the retroactive derivation sweep over documents that predate the epic;
2. the read-outbox drain for agents that have since published;
3. the cross-workspace ``reconcile_aggregate()`` sweep;
4. the dangling-ref repair pass driven by git rename history;
5. the incremental agent/bead touch-index refresh, so a store that drifted
   for any other reason converges off every interactive path.

Job 1 is resumable: a per-project checkpoint of already-swept refs persists
across ticks under a bounded per-tick time budget, so a long tail of
pre-existing documents converges over several hours without redoing already
-processed work, and logs how many documents remain for the next tick.

Job 2's stale-terminal drop runs at most once per day per project and shares
one lazily built agent catalog across every project in a run. Job 3 starts
only when its decaying duration estimate fits in the remaining budget (the
first project of a tick always runs it). A project whose drain or reconcile
work was deferred for budget goes first on the next tick.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.scripts._artifact_link_backfill_jobs import (
    CHOP_NAME,
    BackfillTotals,
    run_project,
)
from sase.scripts._artifact_link_backfill_schedule import (
    SCHEDULE_FILENAME,
    read_backfill_schedule,
    write_backfill_schedule,
)
from sase.scripts._artifact_link_backfill_state import (
    CURSOR_FILENAME,
    STATE_FILENAME,
    next_cursor_after,
    read_project_cursor,
    read_sweep_state,
    rotate_records,
    write_project_cursor,
    write_sweep_state,
)
from sase.sdd._artifact_link_outbox_drain_support import AgentTerminalTimes

_WORKSPACE_HINT_ENV = (
    "SASE_GH_WORKSPACE_DIR",
    "SASE_ACTIVE_PROJECT_DIR",
    "SASE_SDD_DIR",
)
# Bounds only the sweep (job 1); the drain and reconcile/repair jobs already
# bound their own work and run for every project regardless of this budget.
_SWEEP_WORK_BUDGET_SECONDS = 45.0
# Bounds the whole chop, well under the axe-configured 300s timeout, so a
# slowdown degrades into a logged deferral instead of a silent SIGKILL.
_CHOP_WORK_BUDGET_SECONDS = 240.0


def _enabled_project_records() -> list[ProjectRecordWire]:
    records = [
        record
        for record in list_project_records(
            sase_projects_dir(),
            include_states=("enabled",),
            include_home=False,
            projects_only=True,
        )
        if record.is_project and record.workspace_dir
    ]
    return _prefer_current_workspace_record(records, cwd=Path.cwd())


def _prefer_current_workspace_record(
    records: list[ProjectRecordWire], *, cwd: Path
) -> list[ProjectRecordWire]:
    found = _current_workspace_marker(cwd)
    if found is None:
        return records
    workspace_root, marker = found
    project_refs = {
        str(value)
        for value in (marker.project_name, marker.project_key)
        if isinstance(value, str) and value
    }
    if not project_refs:
        return records
    preferred = str(Path(workspace_root).expanduser().resolve(strict=False))
    adjusted: list[ProjectRecordWire] = []
    for record in records:
        names = {
            record.project_name,
            *(record.aliases or ()),
        }
        if record.display_name:
            names.add(record.display_name)
        if project_refs & names:
            adjusted.append(replace(record, workspace_dir=preferred))
        else:
            adjusted.append(record)
    return adjusted


def _current_workspace_marker(cwd: Path) -> tuple[str, Any] | None:
    try:
        from sase.workspace_provider import find_marker_from_cwd
    except Exception:
        return None
    candidates = [
        Path(raw) for key in _WORKSPACE_HINT_ENV if (raw := os.environ.get(key))
    ]
    candidates.append(cwd)
    seen: set[Path] = set()
    for candidate in candidates:
        path = candidate.expanduser().resolve(strict=False)
        if path in seen:
            continue
        seen.add(path)
        try:
            found = find_marker_from_cwd(str(path))
        except Exception:
            continue
        if found is not None:
            return found
    return None


@builtin_chop("artifact_link_backfill")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_path = Path(runtime.context.state_dir) / STATE_FILENAME
    cursor_path = Path(runtime.context.state_dir) / CURSOR_FILENAME
    schedule_path = Path(runtime.context.state_dir) / SCHEDULE_FILENAME
    records = rotate_records(
        _enabled_project_records(), read_project_cursor(cursor_path)
    )
    swept = read_sweep_state(state_path)
    live_keys = {record.project_name for record in records}
    for stale_key in set(swept) - live_keys:
        del swept[stale_key]
    schedule = read_backfill_schedule(schedule_path)
    schedule.prune(live_keys)
    terminal_times = AgentTerminalTimes()

    totals = BackfillTotals()
    deadline = time.monotonic() + _SWEEP_WORK_BUDGET_SECONDS
    chop_deadline = time.monotonic() + _CHOP_WORK_BUDGET_SECONDS
    last_started: str | None = None
    first_deferred: str | None = None
    for index, record in enumerate(records):
        assert record.workspace_dir is not None
        if time.monotonic() >= chop_deadline:
            deferred_names = [r.project_name for r in records[index:]]
            totals.deferred_projects += len(deferred_names)
            totals.warnings.append(
                "job budget exceeded; projects not started: "
                + ", ".join(deferred_names)
            )
            break
        last_started = record.project_name
        deferred = run_project(
            record.project_name,
            record.workspace_dir,
            swept=swept,
            totals=totals,
            deadline=deadline,
            chop_deadline=chop_deadline,
            state_path=state_path,
            runtime=runtime,
            terminal_times=terminal_times,
            schedule=schedule,
            first_project=index == 0,
        )
        if deferred and first_deferred is None:
            first_deferred = record.project_name

    try:
        write_sweep_state(state_path, swept)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        totals.warnings.append(f"failed to persist sweep checkpoint: {exc}")
    try:
        write_backfill_schedule(schedule_path, schedule)
    except Exception as exc:  # noqa: BLE001 - retry on the next tick.
        totals.warnings.append(f"failed to persist backfill schedule: {exc}")
    try:
        write_project_cursor(
            cursor_path,
            first_deferred or next_cursor_after(records, last_started),
        )
    except Exception as exc:  # noqa: BLE001 - fairness retries on the next tick.
        totals.warnings.append(f"failed to persist project cursor: {exc}")

    for warning in totals.warnings:
        runtime.log.warning(f"[{CHOP_NAME}] {warning}")
    if totals.sweep_remaining:
        runtime.log.info(
            f"[{CHOP_NAME}] {totals.sweep_remaining} documents remain unswept; "
            "continuing on later ticks"
        )

    if totals.bead_projection_failed:
        reason = "bead_projection_failed"
    elif totals.projects == 0:
        reason = "no_enabled_projects"
    else:
        reason = None
    result = runtime.emit_summary(
        {
            "projects": totals.projects,
            "touch_index_refreshed": totals.touch_index_refreshed,
            "touch_index_reduced_streams": totals.touch_index_reduced_streams,
            "failed_projects": totals.failed_projects,
            "sweep_scanned": totals.sweep_scanned,
            "sweep_persisted": totals.sweep_persisted,
            "sweep_remaining": totals.sweep_remaining,
            "outbox_drained": totals.outbox_drained,
            "outbox_dropped": totals.outbox_dropped,
            "bead_projection_failed": totals.bead_projection_failed,
            "parked_new": totals.parked_new,
            "parked_total": totals.parked_total,
            "transient": totals.transient,
            "publication_attempted": totals.publication_attempted,
            "publication_published": totals.publication_published,
            "publication_deferred": totals.publication_deferred,
            "publication_failed": totals.publication_failed,
            "publication_aged": totals.publication_aged,
            "publication_discovered": totals.publication_discovered,
            "publication_cleared": totals.publication_cleared,
            "reconciled": totals.reconciled,
            "repaired_renames": totals.repaired_renames,
            "deferred_projects": totals.deferred_projects,
            "stale_checked_projects": totals.stale_checked_projects,
        },
        reason=reason,
    )
    if totals.bead_projection_failed:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("artifact_link_backfill")


if __name__ == "__main__":
    main()
