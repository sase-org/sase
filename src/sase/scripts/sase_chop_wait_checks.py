#!/usr/bin/env python3
"""Wait dependency resolution chop script.

Consults waiting.json markers first and exits no_op before loading
agent_meta.json when nothing is pending. Remaining waits resolve through
the agent artifact index when it is present, else a targeted filesystem
read of referenced artifacts. ``SASE_CHOP_SCAN_FULL_WALK=1`` restores the
legacy full O(all-artifacts) meta walk for parity testing.
"""

import json
import traceback
from dataclasses import dataclass
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.axe.run_agent_wait_deps import mark_bead_wait_sync_hint
from sase.bead.store_locator import closed_bead_ids_for_project
from sase.bead.wait_status import WaitBeadStatusCache, closed_bead_ids_for_waits
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopResultBuilder
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.paths import sase_projects_dir
from sase.core.time import get_timezone
from sase.core.wait_dependency_resolution import (
    KNOWN_DONE_OUTCOMES,
    WaitDependencyIndex,
    confirm_dependency_resolution,
    dependency_resolution_status,
    read_json_dict as _read_json_dict,
)
from sase.core.wait_dependency_resolution._artifact_state import artifact_dir_key
from sase.core.wait_dependency_resolution._types import ArtifactCandidate
from sase.notifications.models import Notification, normalize_notification_tags
from sase.notifications.store import upsert_notification
from sase.scripts._chop_incremental_index import (
    chop_scan_full_walk,
    query_ace_run_index_records,
    wait_rows_from_index_records,
)

_MAX_TERMINAL_BLOCKER_LOGS = 10
_TERMINAL_BLOCKED_WAIT_SENDER = "wait_checks"


@dataclass(frozen=True)
class _WaitingMarker:
    project_name: str
    ready_path: Path
    waiting_path: Path


@dataclass(frozen=True)
class _TerminalBlocker:
    dependency: str
    artifact_dir: str
    outcome: str


@builtin_chop("wait_checks")
def _run(
    runtime: BuiltinChopRuntime,
    *,
    full_walk: bool | None = None,
) -> ChopResultBuilder:
    projects_dir = sase_projects_dir()
    if not projects_dir.exists():
        return runtime.emit_summary(
            {
                "projects": 0,
                "artifacts": 0,
                "waiting": 0,
                "ready_written": 0,
                "deferred_unconfirmed": 0,
            },
            reason="no_projects_dir",
        )

    use_full_walk = chop_scan_full_walk() if full_walk is None else full_walk
    projects = 0
    artifacts = 0
    waiting_markers = 0
    ready_written = 0
    skipped_ready = 0
    skipped_invalid = 0
    unresolved = 0
    unknown_outcome = 0
    deferred_unconfirmed = 0
    waiter_errors = 0
    waiter_error_logs = 0
    terminal_blocker_logs = 0
    terminal_blocker_suppressed = 0
    dependency_index = WaitDependencyIndex.empty()
    pending_waiting_markers: list[_WaitingMarker] = []
    artifact_rows: list[tuple[Path, dict[str, Any], str]] = []
    fresh_indexes: dict[tuple[tuple[str, ...], int], WaitDependencyIndex] = {}
    # Run-scoped agent_meta.json cache. The confirmation pass re-lists artifact
    # directories (so a successor created after the resolving view was built is
    # still detected) but reuses metadata this run already loaded, keeping the
    # scan-once contract. Index rows only read meta dicts, never mutate them.
    meta_cache: dict[Path, dict[str, Any] | None] = {}

    walked_dirs: set[Path] = set()
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        projects += 1

        for artifact_dir in iter_agent_artifact_dirs(
            project_dir.name,
            "ace-run",
            projects_root=projects_dir,
        ):
            artifacts += 1
            walked_dirs.add(artifact_dir)

            waiting_path = artifact_dir / "waiting.json"
            if waiting_path.exists():
                waiting_markers += 1
                ready_path = artifact_dir / "ready.json"
                if ready_path.exists():
                    skipped_ready += 1
                else:
                    pending_waiting_markers.append(
                        _WaitingMarker(
                            project_name=project_dir.name,
                            ready_path=ready_path,
                            waiting_path=waiting_path,
                        )
                    )

            if not use_full_walk:
                continue
            meta_path = artifact_dir / "agent_meta.json"
            if meta_path not in meta_cache:
                meta_cache[meta_path] = _read_json_dict(meta_path)
            meta = meta_cache[meta_path]
            if meta is not None:
                artifact_rows.append((artifact_dir, meta, project_dir.name))

    if pending_waiting_markers:
        if not artifact_rows:
            indexed = query_ace_run_index_records(projects_dir)
            if indexed:
                artifact_rows = wait_rows_from_index_records(indexed)
            if not artifact_rows:
                artifact_rows = _filesystem_dependency_rows(
                    projects_dir, meta_cache=meta_cache
                )
        dependency_index.add_many(artifact_rows)
        # Seed the cache from the resolving view (index records or the walk
        # above) so the confirmation rescan only reads metadata for artifact
        # directories the resolving view never saw: exactly the new-member
        # signal the confirmation exists to detect.
        for artifact_dir, meta, _project_name in artifact_rows:
            meta_cache.setdefault(artifact_dir / "agent_meta.json", meta)
        # Seed negatives for walked directories whose meta file is absent
        # (waiter-only dirs usually): the rescan must not re-stat them into
        # reads, while a directory the walk never saw stays a cache miss and
        # is genuinely re-read.
        for artifact_dir in walked_dirs:
            meta_path = artifact_dir / "agent_meta.json"
            if meta_path not in meta_cache and not meta_path.exists():
                meta_cache[meta_path] = None

    wait_bead_cache = WaitBeadStatusCache()

    def _process_one_waiter(
        waiting_marker: _WaitingMarker,
        data: dict[str, Any],
        waiting_for: list[Any],
        wait_for_artifacts: list[Any],
        wait_for_fork_sources: list[Any],
        wait_for_beads: list[Any],
        wait_for_hoods: list[Any],
        resolved_deps: list[Any],
    ) -> None:
        """Resolve one waiter; any exception parks only this waiter."""
        nonlocal ready_written, skipped_invalid, unresolved, unknown_outcome
        nonlocal deferred_unconfirmed, terminal_blocker_logs
        nonlocal terminal_blocker_suppressed
        closed_bead_ids = None
        if wait_for_beads:
            project_name = waiting_marker.project_name
            closed_bead_ids = closed_bead_ids_for_waits(
                project_name,
                wait_for_beads,
                cache=wait_bead_cache,
                closed_ids_for_project=closed_bead_ids_for_project,
                sync_hint=mark_bead_wait_sync_hint,
            ).closed_ids

        status = dependency_resolution_status(
            dependency_index,
            waiting_for,
            wait_for_artifacts,
            resolved_deps,
            wait_fork_sources=wait_for_fork_sources,
            wait_beads=wait_for_beads,
            wait_hoods=wait_for_hoods,
            closed_bead_ids=closed_bead_ids,
            self_artifact_dir=waiting_marker.waiting_path.parent,
        )
        for diagnostic in status.diagnostics:
            runtime.log(f"[wait_checks] {diagnostic}")
        if status.resolved:
            member_dirs = dependency_index.dependency_member_dirs(
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
                for candidate in dependency_index.artifacts_by_dir.values()
                if artifact_dir_key(candidate.artifact_dir) in member_dirs
                and candidate.project_name
            )
            confirmation_round = 0

            def fresh_index(
                projects: frozenset[str] = frozenset(confirmation_projects),
            ) -> WaitDependencyIndex:
                nonlocal confirmation_round
                key = (tuple(sorted(projects)), confirmation_round)
                confirmation_round += 1
                cached = fresh_indexes.get(key)
                if cached is not None:
                    return cached
                fresh = WaitDependencyIndex.empty(
                    global_stored_tribes=dependency_index.global_stored_tribes,
                )
                # The resolving index may use a custom tribe-evidence path. Keep
                # that already-loaded evidence exactly rather than allowing the
                # confirmation pass to see a different tribe universe.
                fresh.agent_tribes = dict(dependency_index.agent_tribes)
                fresh.add_many(
                    _filesystem_dependency_rows(
                        projects_dir,
                        project_names=set(projects),
                        meta_cache=meta_cache,
                    )
                )
                fresh_indexes[key] = fresh
                return fresh

            try:
                confirmation = confirm_dependency_resolution(
                    dependency_index,
                    fresh_index,
                    waiting_for,
                    wait_for_artifacts,
                    resolved_deps,
                    wait_fork_sources=wait_for_fork_sources,
                    wait_beads=wait_for_beads,
                    wait_hoods=wait_for_hoods,
                    closed_bead_ids=closed_bead_ids,
                    self_artifact_dir=waiting_marker.waiting_path.parent,
                )
            except Exception as exc:  # noqa: BLE001 - a failed confirmation must park.
                deferred_unconfirmed += 1
                runtime.log(
                    "[wait_checks] Deferred release for "
                    f"{data.get('cl_name', 'unknown')}: could not confirm "
                    f"dependency membership ({exc})",
                )
                return
            if not confirmation.confirmed:
                deferred_unconfirmed += 1
                cl_name = data.get("cl_name", "unknown")
                if confirmation.new_member_dirs:
                    runtime.log(
                        "[wait_checks] Deferred release for "
                        f"{cl_name}: dependency membership changed since the "
                        "resolving view (new: "
                        f"{', '.join(confirmation.new_member_dirs)})",
                    )
                else:
                    blocked = ", ".join(confirmation.status.blocked_on)
                    runtime.log(
                        "[wait_checks] Deferred release for "
                        f"{cl_name}: fresh dependency view remains unresolved "
                        f"(blocked on: {blocked or '<unknown>'})",
                    )
                return
            cl_name = data.get("cl_name", "unknown")
            waited_on = ", ".join(waiting_for)
            if wait_for_beads:
                bead_wait = f"beads: {', '.join(wait_for_beads)}"
                waited_on = f"{waited_on}; {bead_wait}" if waited_on else bead_wait
            if wait_for_hoods:
                hood_wait = f"hoods: {', '.join(wait_for_hoods)}"
                waited_on = f"{waited_on}; {hood_wait}" if waited_on else hood_wait
            runtime.log(
                f"[wait_checks] Dependencies satisfied for {cl_name}, "
                f"waited on: {waited_on}",
            )
            try:
                with open(waiting_marker.ready_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"resolved_deps": waiting_for},
                        f,
                        indent=2,
                    )
            except OSError:
                skipped_invalid += 1
            else:
                ready_written += 1
        else:
            unresolved += 1
            terminal_blockers = _terminal_blockers(
                dependency_index,
                waiting_for,
                wait_for_artifacts,
                wait_for_hoods,
                status.blocked_on,
                self_artifact_dir=waiting_marker.waiting_path.parent,
            )
            for blocker in terminal_blockers:
                _upsert_terminal_blocked_wait_notification(
                    waiting_marker,
                    data,
                    blocker,
                )
                if blocker.outcome not in KNOWN_DONE_OUTCOMES:
                    unknown_outcome += 1
                    runtime.log(
                        "[wait_checks] Unknown done outcome blocks waiter "
                        f"{waiting_marker.waiting_path.parent}: "
                        f"dependency={blocker.dependency} "
                        f"artifact={blocker.artifact_dir} "
                        f"outcome={blocker.outcome!r}",
                    )
                if terminal_blocker_logs < _MAX_TERMINAL_BLOCKER_LOGS:
                    terminal_blocker_logs += 1
                    runtime.log(
                        "[wait_checks] Terminal dependency still blocks waiter "
                        f"{waiting_marker.waiting_path.parent}: "
                        f"dependency={blocker.dependency} "
                        f"artifact={blocker.artifact_dir} "
                        f"outcome={blocker.outcome!r}",
                    )
                else:
                    terminal_blocker_suppressed += 1

    for waiting_marker in pending_waiting_markers:
        try:
            with open(waiting_marker.waiting_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            skipped_invalid += 1
            continue

        if not isinstance(data, dict):
            skipped_invalid += 1
            continue

        waiting_for = data.get("waiting_for", [])
        wait_for_artifacts = data.get("wait_for_artifacts", [])
        wait_for_fork_sources = data.get("wait_for_fork_sources", [])
        wait_for_beads = data.get("wait_for_beads", [])
        wait_for_hoods = data.get("wait_for_hoods", [])
        resolved_deps = data.get("resolved_deps", [])
        if not isinstance(wait_for_artifacts, list):
            wait_for_artifacts = []
        if not isinstance(wait_for_fork_sources, list):
            wait_for_fork_sources = []
        if not isinstance(wait_for_beads, list):
            wait_for_beads = []
        if not isinstance(wait_for_hoods, list):
            wait_for_hoods = []
        if not isinstance(resolved_deps, list):
            resolved_deps = []
        if not isinstance(waiting_for, list) or (
            not waiting_for
            and not wait_for_artifacts
            and not wait_for_fork_sources
            and not wait_for_beads
            and not wait_for_hoods
        ):
            skipped_invalid += 1
            continue

        try:
            _process_one_waiter(
                waiting_marker,
                data,
                waiting_for,
                wait_for_artifacts,
                wait_for_fork_sources,
                wait_for_beads,
                wait_for_hoods,
                resolved_deps,
            )
        except Exception as exc:  # noqa: BLE001 - one bad waiter must not stall the tick.
            waiter_errors += 1
            waiter_name = data.get("cl_name", "unknown")
            waiter_dir = waiting_marker.waiting_path.parent
            if waiter_error_logs < _MAX_TERMINAL_BLOCKER_LOGS:
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

    if terminal_blocker_suppressed:
        runtime.log(
            "[wait_checks] Suppressed "
            f"{terminal_blocker_suppressed} additional terminal blocker log(s)",
        )

    reason = None
    if ready_written == 0:
        if projects == 0:
            reason = "no_project_dirs"
        elif waiting_markers == 0:
            reason = "no_waiting_markers"
        elif unresolved > 0:
            reason = "dependencies_not_ready"
        elif skipped_ready > 0:
            reason = "waiting_markers_already_ready"
        else:
            reason = "no_ready_markers_written"
    result = runtime.emit_summary(
        {
            "projects": projects,
            "artifacts": artifacts,
            "waiting": waiting_markers,
            "ready_written": ready_written,
            "already_ready": skipped_ready,
            "invalid": skipped_invalid,
            "unresolved": unresolved,
            "unknown_outcome": unknown_outcome,
            "deferred_unconfirmed": deferred_unconfirmed,
            "waiter_errors": waiter_errors,
        },
        reason=reason,
    )
    if waiter_errors > 0:
        result.status = "check_error"
    return result


def _filesystem_dependency_rows(
    projects_dir: Path,
    *,
    project_names: set[str] | None = None,
    meta_cache: dict[Path, dict[str, Any] | None] | None = None,
) -> list[tuple[Path, dict[str, Any], str]]:
    """Load ace-run agent_meta.json files for wait-dependency resolution.

    When meta_cache is given, reuse metadata already loaded earlier in the run
    and only read files for artifact directories not yet seen. The directory
    listing itself is always fresh.
    """

    rows: list[tuple[Path, dict[str, Any], str]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_names is not None and project_name not in project_names:
            continue
        for artifact_dir in iter_agent_artifact_dirs(
            project_name,
            "ace-run",
            projects_root=projects_dir,
        ):
            meta_path = artifact_dir / "agent_meta.json"
            if meta_cache is not None and meta_path in meta_cache:
                meta = meta_cache[meta_path]
            else:
                meta = _read_json_dict(meta_path)
                if meta_cache is not None:
                    meta_cache[meta_path] = meta
            if meta is not None:
                rows.append((artifact_dir, meta, project_name))
    return rows


def _terminal_blockers(
    dependency_index: WaitDependencyIndex,
    waiting_for: list[object],
    wait_for_artifacts: list[object],
    wait_for_hoods: list[object],
    blocked_on: tuple[str, ...],
    *,
    self_artifact_dir: Path,
) -> tuple[_TerminalBlocker, ...]:
    blocked_labels = frozenset(blocked_on)
    blockers: list[_TerminalBlocker] = []
    identity_names: set[str] = set()

    for dependency in wait_for_artifacts:
        if not isinstance(dependency, Mapping):
            continue
        name = dependency.get("name")
        if isinstance(name, str) and name:
            identity_names.add(name)
        label = _dependency_label(dependency)
        if label not in blocked_labels:
            continue
        candidate = _artifact_candidate_for_identity(dependency_index, dependency)
        if candidate is not None and _identity_terminal_blocker(candidate):
            outcome = candidate.outcome
            assert outcome is not None
            blockers.append(
                _TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=outcome,
                )
            )

    waiter_launch_cutoff = self_artifact_dir.name
    for hood in wait_for_hoods:
        if not isinstance(hood, str):
            continue
        label = f"hood={hood}"
        if label not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_hood(
            hood,
            exclude_artifact_dir=self_artifact_dir,
            launched_at_or_before=waiter_launch_cutoff,
        ):
            assert candidate.outcome is not None
            blockers.append(
                _TerminalBlocker(
                    dependency=label,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                )
            )

    for name in waiting_for:
        if not isinstance(name, str) or name in identity_names:
            continue
        if name not in blocked_labels:
            continue
        for candidate in dependency_index.terminal_blocking_artifacts_for_name(
            name,
            exclude_artifact_dir=self_artifact_dir,
            newer_than=waiter_launch_cutoff if name.startswith("@") else None,
        ):
            assert candidate.outcome is not None
            blockers.append(
                _TerminalBlocker(
                    dependency=name,
                    artifact_dir=candidate.artifact_dir,
                    outcome=candidate.outcome,
                )
            )

    return tuple(blockers)


def _upsert_terminal_blocked_wait_notification(
    waiting_marker: _WaitingMarker,
    waiting_data: Mapping[str, Any],
    blocker: _TerminalBlocker,
) -> None:
    waiter_dir = waiting_marker.waiting_path.parent
    waiter_name = _waiting_agent_label(waiting_data, waiter_dir)
    timestamp = datetime.now(get_timezone()).isoformat()
    recovery = _monitor_not_launchable_recovery(blocker.artifact_dir)
    notes = [
        "Wait dependency can never self-resolve",
        f"Waiter: {waiter_name}",
        (
            f"Blocked on {blocker.dependency}: {blocker.artifact_dir} "
            f"({blocker.outcome})"
        ),
        (
            "Kill and relaunch the waiter, or intentionally clear the wait "
            "once the dependency state is understood."
        ),
    ]
    files = [str(waiter_dir), blocker.artifact_dir]
    action_data: dict[str, Any] = {
        "waiter": waiter_name,
        "waiter_artifact_dir": str(waiter_dir),
        "dependency": blocker.dependency,
        "blocking_artifact_dir": blocker.artifact_dir,
        "blocking_outcome": blocker.outcome,
    }
    if recovery.resume_command:
        notes.append(f"Monitor recovery: `{recovery.resume_command}`")
        action_data["monitor_resume_command"] = recovery.resume_command
    if recovery.snapshot_path:
        notes.append(f"Worktree recovery diff: {recovery.snapshot_path}")
        files.append(recovery.snapshot_path)
        action_data["worktree_recovery_diff_path"] = recovery.snapshot_path
    notification = Notification(
        id=str(uuid4()),
        timestamp=timestamp,
        sender=_TERMINAL_BLOCKED_WAIT_SENDER,
        icon="!",
        color="#D14343",
        notes=notes,
        files=files,
        tags=normalize_notification_tags(["wait", "blocked", "terminal-dependency"]),
        action_data=action_data,
        dedup_key=f"wait_checks:terminal-blocked:{waiter_dir}",
    )
    upsert_notification(
        notification,
        plus_one_note=(
            f"Still blocked on {blocker.dependency}: {blocker.artifact_dir} "
            f"({blocker.outcome})"
        ),
        plus_one_timestamp=timestamp,
    )


@dataclass(frozen=True)
class _MonitorRecovery:
    resume_command: str | None = None
    snapshot_path: str | None = None


def _monitor_not_launchable_recovery(artifact_dir: str) -> _MonitorRecovery:
    done = _read_json_dict(Path(artifact_dir) / "done.json")
    if done is None or done.get("monitor_followup_outcome") != "not-launchable":
        return _MonitorRecovery()
    meta = _read_json_dict(Path(artifact_dir) / "agent_meta.json") or {}
    monitor_id = _string_value(done.get("monitor_id")) or _string_value(
        meta.get("monitor_id")
    )
    snapshot_path = _string_value(
        done.get("monitor_worktree_recovery_diff_path")
    ) or _string_value(meta.get("monitor_worktree_recovery_diff_path"))
    return _MonitorRecovery(
        resume_command=f"sase monitor resume {monitor_id}" if monitor_id else None,
        snapshot_path=snapshot_path,
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _waiting_agent_label(waiting_data: Mapping[str, Any], waiter_dir: Path) -> str:
    cl_name = waiting_data.get("cl_name")
    if isinstance(cl_name, str) and cl_name:
        return cl_name
    return waiter_dir.name


def _artifact_candidate_for_identity(
    dependency_index: WaitDependencyIndex,
    dependency: Mapping[str, Any],
) -> ArtifactCandidate | None:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        candidate = dependency_index.artifacts_by_dir.get(artifact_dir)
        if candidate is not None:
            return candidate

    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if isinstance(project_name, str) and isinstance(timestamp, str):
        return dependency_index.artifacts.get((project_name, timestamp))
    return None


def _identity_terminal_blocker(candidate: ArtifactCandidate) -> bool:
    return (
        candidate.has_done_marker
        and candidate.outcome is not None
        and not candidate.is_identity_success
    )


def _dependency_label(dependency: Mapping[str, Any]) -> str:
    artifact_dir = dependency.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        return artifact_dir
    project_name = dependency.get("project_name")
    timestamp = dependency.get("timestamp")
    if (
        isinstance(project_name, str)
        and project_name
        and isinstance(timestamp, str)
        and timestamp
    ):
        return f"{project_name}:{timestamp}"
    name = dependency.get("name")
    if isinstance(name, str) and name:
        return name
    return "<artifact dependency>"


def main() -> None:
    run_builtin_chop("wait_checks")


if __name__ == "__main__":
    main()
