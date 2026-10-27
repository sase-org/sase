"""Wait_checks run loop and filesystem rows.

Owns the ``wait_checks`` builtin handler, the waiting-marker scan, and the
run-scoped ``agent_meta.json`` cache. Terminal-blocker detection lives in
:mod:`sase.scripts._chop_wait_checks_terminal`; shared dataclasses live in
:mod:`sase.scripts._chop_wait_checks_common`. Filesystem rows live in
:mod:`sase.scripts._chop_wait_checks_run_fs`; per-waiter release lives in
:mod:`sase.scripts._chop_wait_checks_run_waiters`.
"""

from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from sase.axe.wait_marker_scan import scan_waiting_markers, waiting_runner_liveness
from sase.bead.model import Status
from sase.bead.store_locator import bead_statuses_for_project
from sase.bead.wait_status import WaitBeadStatusCache
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.paths import sase_projects_dir
from sase.core.wait_dependency_resolution import (
    ScopeKeyCache,
    WaitDependencyIndex,
    marker_scope_keys,
)
import sase.scripts._chop_wait_checks_run_fs as wait_checks_fs
from sase.scripts._chop_wait_checks_run_fs import (
    clone_empty_index,
    filesystem_dependency_rows,
)
from sase.scripts._chop_wait_checks_common import WaitingMarker
from sase.scripts._chop_wait_checks_stranded import collect_targeted_stranded_report
from sase.scripts._chop_wait_checks_run_waiters import (
    MAX_TERMINAL_BLOCKER_LOGS,
    LiveWaiter,
    WaitChecksTick,
    process_one_waiter,
)
from sase.scripts._chop_wait_checks_terminal import (
    outstanding_stranded_bead_wait_targets,
    reconcile_epic_follow_notifications,
    reconcile_stranded_bead_wait_notifications,
    stranded_bead_wait_dedup_key,
    upsert_stranded_bead_wait_notification,
)


def _as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_live_waiter(waiting_marker: WaitingMarker) -> LiveWaiter | None:
    """Parse a live waiter's marker once. ``None`` means skip as invalid."""
    try:
        with open(waiting_marker.waiting_path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None

    waiting_for = data.get("waiting_for", [])
    wait_for_artifacts = _as_list(data.get("wait_for_artifacts", []))
    wait_for_fork_sources = _as_list(data.get("wait_for_fork_sources", []))
    wait_for_beads = _as_list(data.get("wait_for_beads", []))
    wait_for_hoods = _as_list(data.get("wait_for_hoods", []))
    resolved_deps = _as_list(data.get("resolved_deps", []))
    wait_for_epics_of = _as_list(data.get("wait_for_epics_of", []))
    wait_epic_follows = _as_list(data.get("wait_epic_follows", []))
    if not isinstance(waiting_for, list) or (
        not waiting_for
        and not wait_for_artifacts
        and not wait_for_fork_sources
        and not wait_for_beads
        and not wait_for_hoods
    ):
        return None

    marker = {
        "waiting_for": waiting_for,
        "wait_for_artifacts": wait_for_artifacts,
        "wait_for_fork_sources": wait_for_fork_sources,
        "wait_for_beads": wait_for_beads,
        "wait_for_hoods": wait_for_hoods,
        "resolved_deps": resolved_deps,
        "wait_for_epics_of": wait_for_epics_of,
        "wait_epic_follows": wait_epic_follows,
    }
    return LiveWaiter(
        waiting_marker=waiting_marker,
        data=data,
        waiting_for=waiting_for,
        wait_for_artifacts=wait_for_artifacts,
        wait_for_fork_sources=wait_for_fork_sources,
        wait_for_beads=wait_for_beads,
        wait_for_hoods=wait_for_hoods,
        resolved_deps=resolved_deps,
        wait_for_epics_of=wait_for_epics_of,
        wait_epic_follows=wait_epic_follows,
        scope_keys=marker_scope_keys(marker),
    )


def _marker_has_epic_follows(waiting_path: Path) -> bool:
    """Return whether a waiting marker carries persisted epic follows."""
    try:
        with open(waiting_path, encoding="utf-8") as stream:
            data = json.load(stream)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and bool(data.get("wait_epic_follows"))


def _process_stranded_bead_waits(tick: WaitChecksTick) -> None:
    """Collect each touched project once and publish bead-level wait alerts."""
    now = time.time()
    try:
        outstanding = outstanding_stranded_bead_wait_targets()
    except Exception as exc:  # noqa: BLE001 - alerts must fail open.
        tick.runtime.log(
            "[wait_checks] Stranded-bead notification load failed; "
            f"leaving existing rows unchanged: {exc}"
        )
        outstanding = {}

    projects = set(tick.stranded_bead_ids_by_project) | set(outstanding)
    if not projects:
        return

    for project in sorted(projects):
        pending_ids = tick.stranded_bead_ids_by_project.get(project, set())
        notify_ids = outstanding.get(project, set())
        target_ids = {
            bead_id.strip()
            for bead_id in pending_ids | notify_ids
            if isinstance(bead_id, str) and bead_id.strip()
        }
        if not target_ids:
            continue

        closed_ids = set(tick.stranded_bead_closed_ids_by_project.get(project, set()))
        try:
            status_by_id = bead_statuses_for_project(project, tuple(sorted(target_ids)))
        except Exception as exc:  # noqa: BLE001 - missing status is not resolved.
            tick.runtime.log(
                f"[wait_checks] Stranded-bead status read failed for {project}; "
                f"not treating missing status as resolved: {exc}"
            )
            status_by_id = None
        else:
            if status_by_id is None:
                tick.runtime.log(
                    f"[wait_checks] Stranded-bead status read unavailable for "
                    f"{project}; not treating missing status as resolved"
                )
        if status_by_id is not None:
            closed_ids.update(
                bead_id
                for bead_id in target_ids
                if status_by_id.get(bead_id) == Status.CLOSED.value
            )

        collect_ids = target_ids - closed_ids
        snapshot = None
        if collect_ids:
            try:
                snapshot = collect_targeted_stranded_report(
                    project,
                    collect_ids,
                    now=now,
                )
            except Exception as exc:  # noqa: BLE001 - alerts must fail open.
                tick.runtime.log(
                    f"[wait_checks] Stranded-bead collection failed for {project}; "
                    f"leaving notifications unchanged: {exc}"
                )
                continue

        waiters_by_id = tick.stranded_bead_waiters_by_project.get(project, {})
        dismiss_keys = {
            stranded_bead_wait_dedup_key(project, bead_id) for bead_id in closed_ids
        }
        if snapshot is not None:
            for verdict in snapshot.report.verdicts:
                key = stranded_bead_wait_dedup_key(project, verdict.bead_id)
                if verdict.state in {"owned", "delegated", "settling"}:
                    dismiss_keys.add(key)
                    continue
                if verdict.state != "stranded":
                    continue
                blocked_waiters = waiters_by_id.get(verdict.bead_id, {})
                if not blocked_waiters:
                    continue
                try:
                    upsert_stranded_bead_wait_notification(
                        project,
                        verdict,
                        snapshot.titles.get(verdict.bead_id, ""),
                        tuple(blocked_waiters.values()),
                        now=now,
                    )
                except Exception as exc:  # noqa: BLE001 - alerts never park waiters.
                    tick.runtime.log(
                        f"[wait_checks] Stranded-bead notification failed for "
                        f"{project}:{verdict.bead_id}: {exc}"
                    )

        if dismiss_keys:
            try:
                dismissed = reconcile_stranded_bead_wait_notifications(dismiss_keys)
            except Exception as exc:  # noqa: BLE001 - reconciliation fails open.
                tick.runtime.log(
                    f"[wait_checks] Stranded-bead reconcile failed for {project}: {exc}"
                )
                continue
            if dismissed:
                tick.runtime.log(
                    f"[wait_checks] Cleared {dismissed} resolved stranded-bead "
                    f"notification(s) for {project}"
                )


@builtin_chop("wait_checks")
def _run(
    runtime: BuiltinChopRuntime,
) -> ChopResultBuilder:
    walk_started = time.monotonic()
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return runtime.emit_summary(
            {
                "projects": 0,
                "artifacts": 0,
                "waiting": 0,
                "live_waiting": 0,
                "dead_waiting": 0,
                "unknown_liveness": 0,
                "ready_written": 0,
                "deferred_unconfirmed": 0,
                "walk_ms": 0,
                "view_ms": 0,
                "resolve_ms": 0,
                "view_rows": 0,
                "scoped_waiters": 0,
                "full_view_waiters": 0,
            },
            reason="no_projects_dir",
        )

    projects = 0
    artifacts = 0
    waiting_markers = 0
    waiter_errors = 0
    waiter_error_logs = 0
    live_waiting = 0
    dead_waiting = 0
    unknown_liveness = 0
    live_waiting_markers: list[WaitingMarker] = []
    # Run-scoped agent_meta.json cache. The confirmation pass re-lists artifact
    # directories (so a successor created after the resolving view was built is
    # still detected) but reuses metadata this run already loaded, keeping the
    # scan-once contract. Index rows only read meta dicts, never mutate them.
    meta_cache: dict[Path, dict[str, Any] | None] = {}

    # The shared walk reads no agent_meta.json itself: a tick with no live
    # pending waiter costs only the directory walk plus one meta read per
    # pending waiter for the liveness classification below.
    scan = scan_waiting_markers(projects_dir)
    projects = scan.projects
    artifacts = scan.artifacts
    waiting_markers = scan.waiting
    skipped_ready = scan.already_ready
    epic_follow_seen = False
    epic_follow_reconciled_dirs: set[str] = set()
    for already_ready_marker in scan.already_ready_markers:
        # Already released: any epic-follow blocker rows it owns
        # are stale. Read the marker best-effort so the
        # end-of-tick reconcile can dismiss them.
        if _marker_has_epic_follows(already_ready_marker.waiting_path):
            epic_follow_seen = True
            epic_follow_reconciled_dirs.add(
                str(already_ready_marker.waiting_path.parent)
            )

    for waiting_marker in scan.pending:
        waiter_dir = waiting_marker.waiting_path.parent
        meta_path = waiter_dir / "agent_meta.json"
        meta_cache[meta_path] = wait_checks_fs.read_json_dict(meta_path)
        liveness = waiting_runner_liveness(waiter_dir, meta_cache[meta_path])
        if liveness == "dead":
            # Dead waiters get no resolution, no terminal-blocker
            # notifications, and no logs beyond the backlog counter.
            dead_waiting += 1
            # A dead runner never releases, so any epic-follow blocker rows
            # it owns are stale. The follow stage is mirrored in the meta
            # just read, so the end-of-tick reconcile costs no extra read.
            dead_meta = meta_cache[meta_path]
            if isinstance(dead_meta, dict) and dead_meta.get("wait_epic_follows"):
                epic_follow_seen = True
                epic_follow_reconciled_dirs.add(str(waiter_dir))
            continue
        if liveness == "unknown":
            unknown_liveness += 1
        else:
            live_waiting += 1
        live_waiting_markers.append(waiting_marker)

    walk_ms = int((time.monotonic() - walk_started) * 1000)
    runtime.log(
        "[wait_checks] waiter walk progress: "
        f"projects={projects} artifacts={artifacts} waiting={waiting_markers} "
        f"live={live_waiting} dead={dead_waiting} "
        f"unknown_liveness={unknown_liveness} elapsed_ms={walk_ms}",
    )

    live_waiters: list[LiveWaiter] = []
    scopable_keys: set[str] = set()
    scopable_waiter_dirs: list[Path] = []
    scoped_waiters = 0
    full_view_waiters = 0
    skipped_invalid = 0
    for waiting_marker in live_waiting_markers:
        loaded = _load_live_waiter(waiting_marker)
        if loaded is None:
            skipped_invalid += 1
            continue
        live_waiters.append(loaded)
        if loaded.scope_keys is None:
            full_view_waiters += 1
        else:
            scoped_waiters += 1
            scopable_keys.update(loaded.scope_keys)
            scopable_waiter_dirs.append(waiting_marker.waiting_path.parent)

    view_started = time.monotonic()
    view_ms = 0
    view_rows = 0
    scoped_index: WaitDependencyIndex | None = None
    full_index: WaitDependencyIndex | None = None
    # Persistent scope-key cache: per-artifact keys fingerprinted by
    # agent_meta.json stat data. Only this job writes it (at the end of the
    # tick, when an entry changed); runners read it read-only.
    scope_cache = ScopeKeyCache.load()
    scope_cache_seen: set[Path] = set()
    scope_cache_used = False
    if live_waiters:
        artifact_rows: list[tuple[Path, dict[str, Any], str]] = []
        # Seed negatives for walked directories whose meta file is absent
        # (waiter-only dirs usually): the rescan must not re-stat them into
        # reads, while a directory the walk never saw stays a cache miss and
        # is genuinely re-read.
        for artifact_dir in scan.walked_dirs:
            meta_path = artifact_dir / "agent_meta.json"
            if meta_path not in meta_cache and not meta_path.exists():
                meta_cache[meta_path] = None
        tribe_source = WaitDependencyIndex.empty()
        if scoped_waiters:
            # Scoped selection first: cache misses read meta fresh here and
            # warm the run cache, so the full walk below reuses those reads
            # instead of every meta being read twice on a cold cache.
            scoped_rows = filesystem_dependency_rows(
                projects_dir,
                meta_cache=meta_cache,
                scope_cache=scope_cache,
                scope_keys=scopable_keys,
                include_dirs=scopable_waiter_dirs,
                seen_dirs=scope_cache_seen,
            )
            scope_cache_used = True
            scoped_index = clone_empty_index(tribe_source)
            scoped_index.add_many(scoped_rows)
            view_rows += len(scoped_rows)
            if not full_view_waiters:
                # Drop unselected meta tuples; confirmation re-lists and
                # reuses the cache. Peak index memory stays the scoped view.
                artifact_rows = scoped_rows
        if full_view_waiters:
            artifact_rows = filesystem_dependency_rows(
                projects_dir, meta_cache=meta_cache
            )
            # Seed the run cache from the resolving walk so the confirmation
            # rescan only reads metadata for artifact directories the
            # resolving view never saw: exactly the new-member signal the
            # confirmation exists to detect.
            for artifact_dir, meta, _project_name in artifact_rows:
                meta_cache.setdefault(artifact_dir / "agent_meta.json", meta)
            full_index = clone_empty_index(tribe_source)
            full_index.add_many(artifact_rows)
            view_rows += len(artifact_rows)
    view_ms += int((time.monotonic() - view_started) * 1000)
    runtime.log(
        "[wait_checks] resolving view progress: "
        f"rows={view_rows} scoped_waiters={scoped_waiters} "
        f"full_view_waiters={full_view_waiters} elapsed_ms={view_ms}",
    )

    tick = WaitChecksTick(
        runtime=runtime,
        projects_dir=projects_dir,
        meta_cache=meta_cache,
        scope_cache=scope_cache,
        scope_cache_seen=scope_cache_seen,
        fresh_indexes={},
        wait_bead_cache=WaitBeadStatusCache(),
        skipped_ready=skipped_ready,
        skipped_invalid=skipped_invalid,
        epic_follow_seen=epic_follow_seen,
        epic_follow_reconciled_dirs=epic_follow_reconciled_dirs,
        view_ms=view_ms,
        view_rows=view_rows,
        scope_cache_used=scope_cache_used,
    )

    resolve_started = time.monotonic()
    for waiter in live_waiters:
        waiting_marker = waiter.waiting_marker
        data = waiter.data
        if waiter.scope_keys is None:
            waiter_index = full_index
        else:
            waiter_index = scoped_index
        if waiter_index is None:
            waiter_errors += 1
            continue
        try:
            process_one_waiter(waiter, waiter_index, tick)
        except Exception as exc:  # noqa: BLE001 - one bad waiter must not stall the tick.
            waiter_errors += 1
            waiter_name = data.get("cl_name", "unknown")
            waiter_dir = waiting_marker.waiting_path.parent
            if waiter_error_logs < MAX_TERMINAL_BLOCKER_LOGS:
                waiter_error_logs += 1
                runtime.log(
                    f"[wait_checks] Waiter {waiter_dir} ({waiter_name}) "
                    f"failed: {exc}\n{traceback.format_exc()}",
                )
            else:
                runtime.log(
                    f"[wait_checks] Waiter {waiter_dir} ({waiter_name}) failed: {exc}",
                )
            continue

    _process_stranded_bead_waits(tick)

    resolve_ms = int((time.monotonic() - resolve_started) * 1000)

    if tick.terminal_blocker_suppressed:
        runtime.log(
            "[wait_checks] Suppressed "
            f"{tick.terminal_blocker_suppressed} additional terminal blocker log(s)",
        )

    if tick.scope_cache_used:
        # Only this job writes the cache, and only when an entry changed.
        # Dirs the tick never listed have vanished: drop them. The write is
        # atomic and best-effort, so it can never fail the tick.
        tick.scope_cache.drop_missing(tick.scope_cache_seen)
        tick.scope_cache.save_if_changed()

    if tick.epic_follow_seen and tick.epic_follow_reconciled_dirs:
        try:
            cleared = reconcile_epic_follow_notifications(
                tick.epic_follow_active_keys, tick.epic_follow_reconciled_dirs
            )
        except Exception as exc:  # noqa: BLE001 - reconcile never fails.
            runtime.log(f"[wait_checks] Epic-follow reconcile failed: {exc}")
            cleared = 0
        if cleared:
            runtime.log(
                f"[wait_checks] Cleared {cleared} resolved epic-follow notification(s)",
            )

    reason = None
    if tick.ready_written == 0:
        if projects == 0:
            reason = "no_project_dirs"
        elif waiting_markers == 0:
            reason = "no_waiting_markers"
        elif tick.unresolved > 0:
            reason = "dependencies_not_ready"
        elif dead_waiting > 0 and live_waiting == 0 and unknown_liveness == 0:
            reason = "no_live_waiters"
        elif tick.skipped_ready > 0:
            reason = "waiting_markers_already_ready"
        else:
            reason = "no_ready_markers_written"
    result = runtime.emit_summary(
        {
            "projects": projects,
            "artifacts": artifacts,
            "waiting": waiting_markers,
            "live_waiting": live_waiting,
            "dead_waiting": dead_waiting,
            "unknown_liveness": unknown_liveness,
            "ready_written": tick.ready_written,
            "already_ready": tick.skipped_ready,
            "invalid": tick.skipped_invalid,
            "unresolved": tick.unresolved,
            "unknown_outcome": tick.unknown_outcome,
            "deferred_unconfirmed": tick.deferred_unconfirmed,
            "waiter_errors": waiter_errors,
            "walk_ms": walk_ms,
            "view_ms": tick.view_ms,
            "resolve_ms": resolve_ms,
            "view_rows": tick.view_rows,
            "scoped_waiters": scoped_waiters,
            "full_view_waiters": full_view_waiters,
        },
        reason=reason,
    )
    if waiter_errors > 0:
        result.status = "check_error"
    return result


def main() -> None:
    run_builtin_chop("wait_checks")


__all__ = ["main"]
