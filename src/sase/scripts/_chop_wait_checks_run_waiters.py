"""Per-waiter resolution for the wait_checks chop.

Owns live-waiter records, tick counters, and the one-waiter release path.
The run loop imports these public names from this already-private module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_deps import mark_bead_wait_sync_hint
from sase.axe.run_agent_wait_markers import publish_ready_marker
from sase.bead.store_locator import closed_bead_ids_for_project
from sase.bead.wait_status import WaitBeadStatusCache, closed_bead_ids_for_waits
from sase.chops.builtin import BuiltinChopRuntime
from sase.core.wait_dependency_resolution import (
    KNOWN_DONE_OUTCOMES,
    ScopeKeyCache,
    WaitDependencyIndex,
    apply_wait_epic_follow_patch,
    latest_member_finished_at,
    resolve_wait_release,
)
from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.scripts._chop_wait_checks_common import (
    StrandedBeadWaiter,
    TerminalBlocker,
    WaitingMarker,
)
from sase.scripts._chop_wait_checks_run_fs import (
    clone_empty_index,
    filesystem_dependency_rows,
)
from sase.scripts._chop_wait_checks_terminal import (
    epic_follow_blocked_dedup_key,
    epic_follow_land_failed_dedup_key,
    epic_follow_launching_dedup_key,
    terminal_blockers,
    upsert_epic_follow_blocked_notification,
    upsert_epic_follow_land_failed_notification,
    upsert_epic_follow_launching_notification,
    upsert_terminal_blocked_wait_notification,
)

MAX_TERMINAL_BLOCKER_LOGS = 10

type _FreshIndexKey = tuple[
    tuple[str, ...],
    int,
    tuple[tuple[str, ...], str] | None,
]


@dataclass(frozen=True)
class LiveWaiter:
    """One live waiter whose waiting.json was already parsed this tick."""

    waiting_marker: WaitingMarker
    data: dict[str, Any]
    waiting_for: list[Any]
    wait_for_artifacts: list[Any]
    wait_for_fork_sources: list[Any]
    wait_for_beads: list[Any]
    wait_for_hoods: list[Any]
    resolved_deps: list[Any]
    wait_for_epics_of: list[Any]
    wait_epic_follows: list[Any]
    scope_keys: frozenset[str] | None


@dataclass
class WaitChecksTick:
    """Mutable per-tick counters and caches shared with waiter processing."""

    runtime: BuiltinChopRuntime
    projects_dir: Path
    meta_cache: dict[Path, dict[str, Any] | None]
    scope_cache: ScopeKeyCache
    scope_cache_seen: set[Path]
    fresh_indexes: dict[_FreshIndexKey, WaitDependencyIndex]
    wait_bead_cache: WaitBeadStatusCache
    ready_written: int = 0
    skipped_ready: int = 0
    skipped_invalid: int = 0
    unresolved: int = 0
    unknown_outcome: int = 0
    deferred_unconfirmed: int = 0
    terminal_blocker_logs: int = 0
    terminal_blocker_suppressed: int = 0
    epic_follow_seen: bool = False
    epic_follow_active_keys: set[str] = field(default_factory=set)
    epic_follow_reconciled_dirs: set[str] = field(default_factory=set)
    stranded_bead_ids_by_project: dict[str, set[str]] = field(default_factory=dict)
    stranded_bead_closed_ids_by_project: dict[str, set[str]] = field(
        default_factory=dict
    )
    stranded_bead_waiters_by_project: dict[
        str, dict[str, dict[str, StrandedBeadWaiter]]
    ] = field(default_factory=dict)
    view_ms: int = 0
    view_rows: int = 0
    scope_cache_used: bool = False


def _epic_follow_notification_keys(
    runtime: BuiltinChopRuntime,
    waiting_marker: WaitingMarker,
    data: dict[str, Any],
    wait_epic_follows: list[Any],
    follows: Any,
    waiter_index: WaitDependencyIndex,
) -> set[str]:
    """Upsert epic-follow blocker notifications; return active dedup keys.

    Merges fresh follow decisions with persisted FOLLOWING entries (pinned
    follows skip the collector) so a land agent that fails after pinning
    still notifies. Never raises: notification failures must not park the
    waiter or block its release.
    """
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_str = str(waiter_dir)
    active: set[str] = set()
    try:
        fresh_by_target = {
            decision.target: decision
            for decision in follows
            if getattr(decision, "target", None)
        }
        following_epics: list[str] = []
        for decision in follows:
            state = getattr(decision, "state", None)
            target = getattr(decision, "target", None)
            if not isinstance(target, str) or not target:
                continue
            if state == "launching" and bool(
                getattr(decision, "launching_overdue", False)
            ):
                upsert_epic_follow_launching_notification(
                    waiting_marker, data, decision
                )
                active.add(epic_follow_launching_dedup_key(waiter_str, target))
            elif state == "blocked":
                upsert_epic_follow_blocked_notification(waiting_marker, data, decision)
                active.add(epic_follow_blocked_dedup_key(waiter_str, target))
            if state == "following":
                for epic_id in getattr(decision, "epic_ids", ()):
                    if isinstance(epic_id, str) and epic_id:
                        following_epics.append(epic_id)
        for entry in wait_epic_follows:
            if not isinstance(entry, dict):
                continue
            target = entry.get("target")
            if not isinstance(target, str) or target in fresh_by_target:
                continue
            if entry.get("state") != "following":
                continue
            epic_ids = entry.get("epic_ids")
            if isinstance(epic_ids, list):
                for epic_id in epic_ids:
                    if isinstance(epic_id, str) and epic_id:
                        following_epics.append(epic_id)
        for epic_id in dict.fromkeys(following_epics):
            try:
                land_blockers = waiter_index.terminal_blocking_artifacts_for_name(
                    f"{epic_id}.land",
                    exclude_artifact_dir=waiter_dir,
                )
            except Exception:  # noqa: BLE001 - best-effort land check.
                continue
            for blocker in land_blockers:
                if blocker.outcome is None:
                    continue
                land_name = blocker.name or f"{epic_id}.land"
                upsert_epic_follow_land_failed_notification(
                    waiting_marker,
                    data,
                    epic_id,
                    land_name,
                    blocker.artifact_dir,
                    blocker.outcome,
                )
                active.add(epic_follow_land_failed_dedup_key(waiter_str, epic_id))
    except Exception as exc:  # noqa: BLE001 - notifications never park.
        runtime.log(
            f"[wait_checks] Epic-follow notification failed for {waiter_dir}: {exc}",
        )
    return active


def _record_stranded_bead_waits(
    tick: WaitChecksTick,
    waiter: LiveWaiter,
    blocked_on: tuple[str, ...],
    closed_bead_ids: frozenset[str] | set[str] | None,
) -> None:
    """Remember bead waits for one post-resolution project collection."""
    bead_ids = tuple(
        dict.fromkeys(
            bead_id.strip()
            for bead_id in waiter.wait_for_beads
            if isinstance(bead_id, str) and bead_id.strip()
        )
    )
    if not bead_ids:
        return
    project = waiter.waiting_marker.project_name
    tick.stranded_bead_ids_by_project.setdefault(project, set()).update(bead_ids)
    if closed_bead_ids is not None:
        tick.stranded_bead_closed_ids_by_project.setdefault(project, set()).update(
            bead_id for bead_id in bead_ids if bead_id in closed_bead_ids
        )

    blocked = set(blocked_on)
    waiter_dir = str(waiter.waiting_marker.waiting_path.parent)
    waiter_name = waiter.data.get("cl_name")
    if not isinstance(waiter_name, str) or not waiter_name:
        waiter_name = waiter.waiting_marker.waiting_path.parent.name
    per_project = tick.stranded_bead_waiters_by_project.setdefault(project, {})
    for bead_id in bead_ids:
        if bead_id not in blocked or (
            closed_bead_ids is not None and bead_id in closed_bead_ids
        ):
            continue
        per_project.setdefault(bead_id, {}).setdefault(
            waiter_dir,
            StrandedBeadWaiter(name=waiter_name, artifact_dir=waiter_dir),
        )


def process_one_waiter(
    waiter: LiveWaiter,
    waiter_index: WaitDependencyIndex,
    tick: WaitChecksTick,
) -> None:
    """Resolve one waiter; any exception parks only this waiter."""
    waiting_marker = waiter.waiting_marker
    data = waiter.data
    waiting_for = waiter.waiting_for
    wait_for_artifacts = waiter.wait_for_artifacts
    wait_for_fork_sources = waiter.wait_for_fork_sources
    wait_for_beads = waiter.wait_for_beads
    wait_for_hoods = waiter.wait_for_hoods
    resolved_deps = waiter.resolved_deps
    wait_for_epics_of = waiter.wait_for_epics_of
    wait_epic_follows = waiter.wait_epic_follows
    scope_keys = waiter.scope_keys
    closed_bead_ids = None
    if wait_for_beads:
        project_name = waiting_marker.project_name
        closed_bead_ids = closed_bead_ids_for_waits(
            project_name,
            wait_for_beads,
            cache=tick.wait_bead_cache,
            closed_ids_for_project=closed_bead_ids_for_project,
            sync_hint=mark_bead_wait_sync_hint,
        ).closed_ids

    member_dirs = waiter_index.dependency_member_dirs(
        waiting_for,
        wait_for_artifacts,
        resolved_deps,
        wait_fork_sources=wait_for_fork_sources,
        wait_hoods=wait_for_hoods,
        self_artifact_dir=waiting_marker.waiting_path.parent,
    )
    confirmation_projects = {waiting_marker.project_name}
    confirmation_projects.update(
        candidate.project_name
        for candidate in waiter_index.artifacts_by_dir.values()
        if artifact_dir_key(candidate.artifact_dir) in member_dirs
        and candidate.project_name
    )
    confirmation_round = 0
    if scope_keys is None:
        scope_token: tuple[tuple[str, ...], str] | None = None
    else:
        scope_token = (
            tuple(sorted(scope_keys)),
            str(waiting_marker.waiting_path.parent),
        )

    def fresh_index(
        projects: frozenset[str] = frozenset(confirmation_projects),
    ) -> WaitDependencyIndex:
        nonlocal confirmation_round
        key = (tuple(sorted(projects)), confirmation_round, scope_token)
        confirmation_round += 1
        cached = tick.fresh_indexes.get(key)
        if cached is not None:
            return cached
        fresh = clone_empty_index(waiter_index)
        fresh_started = time.monotonic()
        if scope_keys is not None:
            # Scoped confirmation re-lists fresh but stats instead of
            # reading: new dirs are cache misses and still read meta,
            # which preserves the new-member signal.
            fresh_rows = filesystem_dependency_rows(
                tick.projects_dir,
                project_names=set(projects),
                meta_cache=tick.meta_cache,
                scope_cache=tick.scope_cache,
                scope_keys=scope_keys,
                include_dirs=(waiting_marker.waiting_path.parent,),
                seen_dirs=tick.scope_cache_seen,
            )
            tick.scope_cache_used = True
        else:
            fresh_rows = filesystem_dependency_rows(
                tick.projects_dir,
                project_names=set(projects),
                meta_cache=tick.meta_cache,
            )
        fresh.add_many(fresh_rows)
        tick.view_ms += int((time.monotonic() - fresh_started) * 1000)
        tick.view_rows += len(fresh_rows)
        tick.fresh_indexes[key] = fresh
        return fresh

    marker: dict[str, Any] = {
        "waiting_for": waiting_for,
        "wait_for_artifacts": wait_for_artifacts,
        "wait_for_fork_sources": wait_for_fork_sources,
        "wait_for_beads": wait_for_beads,
        "wait_for_hoods": wait_for_hoods,
        "resolved_deps": resolved_deps,
        "wait_for_epics_of": wait_for_epics_of,
        "wait_epic_follows": wait_epic_follows,
    }
    try:
        decision = resolve_wait_release(
            waiter_index,
            marker,
            waiter_dir=waiting_marker.waiting_path.parent,
            closed_bead_ids=closed_bead_ids,
            now=time.time(),
            fresh_index=fresh_index,
        )
    except Exception as exc:  # noqa: BLE001 - a failed release check must park.
        tick.deferred_unconfirmed += 1
        tick.runtime.log(
            "[wait_checks] Deferred release for "
            f"{data.get('cl_name', 'unknown')}: could not confirm "
            f"dependency membership ({exc})",
        )
        return
    status = decision.status
    for diagnostic in status.diagnostics:
        tick.runtime.log(f"[wait_checks] {diagnostic}")
    if decision.confirmation_failed:
        tick.deferred_unconfirmed += 1
        cl_name = data.get("cl_name", "unknown")
        if status.resolved:
            tick.runtime.log(
                "[wait_checks] Deferred release for "
                f"{cl_name}: dependency membership changed since the "
                "resolving view",
            )
        else:
            blocked = ", ".join(status.blocked_on)
            tick.runtime.log(
                "[wait_checks] Deferred release for "
                f"{cl_name}: fresh dependency view remains unresolved "
                f"(blocked on: {blocked or '<unknown>'})",
            )
        return
    _record_stranded_bead_waits(tick, waiter, status.blocked_on, closed_bead_ids)
    if wait_for_epics_of or wait_epic_follows:
        tick.epic_follow_seen = True
    if decision.patch is not None:
        apply_wait_epic_follow_patch(waiting_marker.waiting_path.parent, decision.patch)
        tick.epic_follow_active_keys.update(
            _epic_follow_notification_keys(
                tick.runtime,
                waiting_marker,
                data,
                wait_epic_follows,
                decision.follows,
                waiter_index,
            )
        )
        tick.epic_follow_reconciled_dirs.add(str(waiting_marker.waiting_path.parent))
        tick.unresolved += 1
        return
    # Gate on the shared releasable verdict, not the pre-follow status:
    # a persisted-but-unchanged LAUNCHING/BLOCKED follow leaves no patch
    # yet must still hold the waiter (never release on a timeout).
    if decision.releasable:
        if wait_for_epics_of or wait_epic_follows:
            tick.epic_follow_reconciled_dirs.add(
                str(waiting_marker.waiting_path.parent)
            )
        cl_name = data.get("cl_name", "unknown")
        waited_on = ", ".join(waiting_for)
        if wait_for_beads:
            bead_wait = f"beads: {', '.join(wait_for_beads)}"
            waited_on = f"{waited_on}; {bead_wait}" if waited_on else bead_wait
        if wait_for_hoods:
            hood_wait = f"hoods: {', '.join(wait_for_hoods)}"
            waited_on = f"{waited_on}; {hood_wait}" if waited_on else hood_wait
        tick.runtime.log(
            f"[wait_checks] Dependencies satisfied for {cl_name}, "
            f"waited on: {waited_on}",
        )
        ready_payload: dict[str, Any] = {
            "resolved_deps": waiting_for,
            "released_by": "wait_checks",
        }
        if not wait_for_beads:
            satisfied_at = latest_member_finished_at(member_dirs)
            if satisfied_at is not None:
                ready_payload["dependencies_satisfied_at"] = satisfied_at
        try:
            published = publish_ready_marker(
                str(waiting_marker.waiting_path.parent),
                ready_payload,
            )
        except OSError:
            tick.skipped_invalid += 1
        else:
            if published:
                tick.ready_written += 1
            else:
                # Lost the publish race (another writer published
                # first) or the waiter already released and cleaned up.
                tick.skipped_ready += 1
    else:
        tick.unresolved += 1
        if wait_for_epics_of or wait_epic_follows:
            tick.epic_follow_active_keys.update(
                _epic_follow_notification_keys(
                    tick.runtime,
                    waiting_marker,
                    data,
                    wait_epic_follows,
                    decision.follows,
                    waiter_index,
                )
            )
            tick.epic_follow_reconciled_dirs.add(
                str(waiting_marker.waiting_path.parent)
            )
        found_blockers: tuple[TerminalBlocker, ...] = terminal_blockers(
            waiter_index,
            waiting_for,
            wait_for_artifacts,
            wait_for_hoods,
            status.blocked_on,
            self_artifact_dir=waiting_marker.waiting_path.parent,
        )
        for blocker in found_blockers:
            if blocker.dependency in {
                bead_id for bead_id in wait_for_beads if isinstance(bead_id, str)
            }:
                continue
            upsert_terminal_blocked_wait_notification(
                waiting_marker,
                data,
                blocker,
            )
            if blocker.outcome not in KNOWN_DONE_OUTCOMES:
                tick.unknown_outcome += 1
                tick.runtime.log(
                    "[wait_checks] Unknown done outcome blocks waiter "
                    f"{waiting_marker.waiting_path.parent}: "
                    f"dependency={blocker.dependency} "
                    f"artifact={blocker.artifact_dir} "
                    f"outcome={blocker.outcome!r}",
                )
            if tick.terminal_blocker_logs < MAX_TERMINAL_BLOCKER_LOGS:
                tick.terminal_blocker_logs += 1
                tick.runtime.log(
                    "[wait_checks] Terminal dependency still blocks waiter "
                    f"{waiting_marker.waiting_path.parent}: "
                    f"dependency={blocker.dependency} "
                    f"artifact={blocker.artifact_dir} "
                    f"outcome={blocker.outcome!r}",
                )
            else:
                tick.terminal_blocker_suppressed += 1


__all__ = [
    "LiveWaiter",
    "MAX_TERMINAL_BLOCKER_LOGS",
    "WaitChecksTick",
    "process_one_waiter",
]
