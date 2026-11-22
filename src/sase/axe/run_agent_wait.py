"""Dependency and time-based waiting helpers for the run agent runner.

The implementation is split by responsibility:
- ``run_agent_wait_markers`` persists ``waiting.json`` and the durable
  ``wait_completed_at`` stamp.
- ``run_agent_wait_deps`` resolves agent, artifact, and bead dependencies.
- ``run_agent_wait_slots`` enforces the global participating-agent cap.

This module owns the barrier itself: the wait that a runner blocks on before it
starts its workflow.
"""

import json
import os
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_deps import (
    mark_bead_wait_sync_hint,
    read_ready_result,
    resolve_initial_wait_release,
    waiting_marker_dependencies_resolved,
)
from sase.core.wait_dependency_resolution import set_waiting_until
from sase.axe.run_agent_wait_markers import (
    record_wait_completed_at,
    write_waiting_marker,
)
from sase.axe.runner_idle_memory import (
    IDLE_TRIM_INTERVAL_SECONDS,
    release_idle_memory,
)
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.axe.runner_signals import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

_WAIT_DEPENDENCY_FALLBACK_INTERVAL = 60.0
_WAIT_BEAD_HINT_FALLBACK_INTERVAL = 600.0
_WAIT_READY_POLL_INTERVAL = 0.5
_WAIT_TIME_POLL_INTERVAL = 2.0
LEAN_WAIT_HANDOFF_AFTER_SECONDS = 30.0


def remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    from sase.core.time import local_now

    target = dt_cls.fromisoformat(wait_until)
    now = dt_cls.now(target.tzinfo) if target.tzinfo is not None else local_now()
    return max(0.0, (target - now).total_seconds())


def _identity_dep_label(dep: dict[str, Any]) -> str:
    if dep.get("target") == "turn":
        turn_name = dep.get("turn_name")
        if isinstance(turn_name, str) and turn_name:
            return turn_name
    name = dep.get("name")
    if isinstance(name, str) and name:
        return name
    project_name = dep.get("project_name")
    timestamp = dep.get("timestamp")
    if isinstance(project_name, str) and project_name and isinstance(timestamp, str):
        return f"{project_name}:{timestamp}"
    artifact_dir = dep.get("artifact_dir")
    if isinstance(artifact_dir, str) and artifact_dir:
        return artifact_dir
    return "artifact dependency"


def _remove_wait_markers(artifacts_dir: str) -> None:
    """Remove both rendezvous markers and refresh the index after mutation."""
    changed = False
    for filename in ("waiting.json", "ready.json"):
        try:
            os.unlink(os.path.join(artifacts_dir, filename))
            changed = True
        except OSError:
            pass
    if changed:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def _resume_lean_wait_result(
    result: Mapping[str, Any],
    *,
    artifacts_dir: str,
    agent_meta: dict[str, Any],
    has_dependencies: bool,
    wait_beads: list[str],
    duration: float | None,
    wait_until: str | None,
) -> bool:
    """Finish a lean wait after the refreshed runner returns from exec."""
    if result.get("outcome") != "released":
        raise ValueError("only a released lean-wait result can resume the barrier")
    source = result.get("release_source")
    if source not in {"ready_json", "manual", "runner_fallback", "timer"}:
        raise ValueError("released lean-wait result has an invalid release_source")
    satisfied_at = result.get("dependencies_satisfied_at")
    if not isinstance(satisfied_at, (int, float)) or isinstance(satisfied_at, bool):
        satisfied_at = None
    released_at = result.get("released_at")
    if not isinstance(released_at, (int, float)) or isinstance(released_at, bool):
        released_at = None
    if wait_beads:
        # Bead-close times are not observable, even when the lean waiter was
        # released by a probe rather than wait_checks' ready marker.
        satisfied_at = None

    post_dependency_wait_until = wait_until
    if has_dependencies and duration is not None and duration > 0 and not was_killed():
        base = released_at if released_at is not None else time.time()
        deadline = datetime.fromtimestamp(base, UTC) + timedelta(seconds=duration)
        post_dependency_wait_until = deadline.isoformat()
        set_waiting_until(artifacts_dir, post_dependency_wait_until)

    if has_dependencies and post_dependency_wait_until is not None and not was_killed():
        remaining = remaining_until(post_dependency_wait_until)
        if remaining > 0:
            print(f"Dependencies satisfied, waiting until {post_dependency_wait_until}")
            while remaining > 0 and not was_killed():
                time.sleep(min(_WAIT_TIME_POLL_INTERVAL, remaining))
                remaining = remaining_until(post_dependency_wait_until)

    if not was_killed():
        record_wait_completed_at(
            artifacts_dir,
            agent_meta,
            wait_release_source=source,
            wait_dependencies_satisfied_at=satisfied_at,
            wait_released_at=released_at,
        )
    _remove_wait_markers(artifacts_dir)
    print(f"Lean waiter returned to runner (outcome=released, source={source})")
    return True


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    project_name: str | None = None,
    wait_identity_deps: list[dict[str, Any]] | None = None,
    wait_fork_sources: list[dict[str, Any]] | None = None,
    wait_beads: list[str] | None = None,
    wait_hoods: list[str] | None = None,
    duration: float | None = None,
    wait_until: str | None = None,
    wait_for_epics_of: list[str] | None = None,
    lean_wait_handoff: Callable[[str, float | None, float], bool] | None = None,
    lean_wait_result: Mapping[str, Any] | None = None,
) -> bool:
    """Wait for named agent dependencies, a duration, or an absolute time.

    When agent or bead dependencies are present, writes waiting.json and polls
    for ready.json, periodically resolving the dependencies directly as a
    fallback. When *duration* is set alongside dependencies, the duration starts
    after dependency resolution; without dependencies, the duration starts
    immediately. When *wait_until* is set (ISO 8601 timestamp), the agent won't
    start before that wall-clock time.

    Returns whether the process actually blocked. Exits with SIGTERM code if
    killed during the wait.
    """
    mark_lifecycle_phase(artifacts_dir, "waiting")

    wait_identity_deps = list(wait_identity_deps or [])
    wait_fork_sources = list(wait_fork_sources or [])
    wait_beads = list(wait_beads or [])
    wait_hoods = list(wait_hoods or [])
    wait_for_epics_of = list(wait_for_epics_of or [])
    has_dependencies = bool(
        wait_names
        or wait_identity_deps
        or wait_fork_sources
        or wait_beads
        or wait_hoods
    )

    if lean_wait_result is not None:
        return _resume_lean_wait_result(
            lean_wait_result,
            artifacts_dir=artifacts_dir,
            agent_meta=agent_meta,
            has_dependencies=has_dependencies,
            wait_beads=wait_beads,
            duration=duration,
            wait_until=wait_until,
        )

    # A refreshed runner has already crossed the barrier. This durable fast path
    # also prevents duration and mixed dependency waits from running twice.
    existing_wait_completed_at = agent_meta.get("wait_completed_at")
    if not (isinstance(existing_wait_completed_at, str) and existing_wait_completed_at):
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        try:
            with open(meta_path, encoding="utf-8") as f:
                disk_meta = json.load(f)
            disk_wait_completed_at = (
                disk_meta.get("wait_completed_at")
                if isinstance(disk_meta, dict)
                else None
            )
            if isinstance(disk_wait_completed_at, str) and disk_wait_completed_at:
                existing_wait_completed_at = disk_wait_completed_at
                agent_meta["wait_completed_at"] = disk_wait_completed_at
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    if isinstance(existing_wait_completed_at, str) and existing_wait_completed_at:
        print("Dependency wait already completed, proceeding without waiting")
        return False

    blocked = False
    initial_decision = (
        resolve_initial_wait_release(
            wait_names,
            wait_identity_deps,
            wait_fork_sources=wait_fork_sources,
            wait_beads=wait_beads,
            wait_hoods=wait_hoods,
            wait_for_epics_of=wait_for_epics_of,
            project_name=project_name,
            artifacts_dir=artifacts_dir,
        )
        if has_dependencies and duration is None and wait_until is None
        else None
    )
    dependencies_already_resolved = (
        initial_decision.releasable if initial_decision is not None else False
    )

    if (
        has_dependencies
        and duration is None
        and wait_until is None
        and dependencies_already_resolved
    ):
        print("Dependencies already satisfied, proceeding without waiting")
        if not was_killed():
            record_wait_completed_at(
                artifacts_dir, agent_meta, wait_release_source="startup"
            )
        return False

    # Every branch below parks this process. The bootstrap that ran before this
    # call peaked near half a gigabyte and has already dropped almost all of
    # it, so hand those pages back now rather than holding them for the whole
    # wait -- which is hours on a busy host, across dozens of parked runners.
    release_idle_memory()

    if has_dependencies:
        # --- Dependency path (with optional duration/time floor) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        waiting_data: dict[str, Any] = {
            "waiting_for": wait_names,
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
        }
        if wait_identity_deps:
            waiting_data["wait_for_artifacts"] = wait_identity_deps
        if wait_fork_sources:
            waiting_data["wait_for_fork_sources"] = wait_fork_sources
        if wait_beads:
            waiting_data["wait_for_beads"] = wait_beads
        if wait_hoods:
            waiting_data["wait_for_hoods"] = wait_hoods
        if wait_for_epics_of:
            assert set(wait_for_epics_of) <= set(wait_names)
            waiting_data["wait_for_epics_of"] = list(wait_for_epics_of)
        if duration is not None:
            waiting_data["wait_duration"] = duration
        if wait_until is not None:
            waiting_data["wait_until"] = wait_until
        if initial_decision is not None and initial_decision.patch is not None:
            waiting_data["wait_for_beads"] = list(initial_decision.patch.wait_for_beads)
            waiting_data["resolved_deps"] = list(initial_decision.patch.resolved_deps)
            waiting_data["wait_epic_follows"] = [
                dict(entry) for entry in initial_decision.patch.wait_epic_follows
            ]
        write_waiting_marker(artifacts_dir, waiting_data)

        parts = []
        if wait_names:
            parts.append(f"agents: {', '.join(wait_names)}")
        if wait_identity_deps:
            parts.append(
                "artifacts: "
                + ", ".join(_identity_dep_label(dep) for dep in wait_identity_deps)
            )
        if wait_beads:
            parts.append(f"beads: {', '.join(wait_beads)}")
        if wait_hoods:
            parts.append(f"hoods: {', '.join(wait_hoods)}")
        if duration is not None:
            parts.append(f"duration: {duration:.0f}s")
        if wait_until is not None:
            parts.append(f"until: {wait_until}")
        print(f"Waiting for {' and '.join(parts)}")

        # Poll primarily for ready.json (written by the wait_checks lumberjack
        # chop), with a coarse direct-resolution fallback so chop outages cannot
        # strand the runner forever.
        ready_path = os.path.join(artifacts_dir, "ready.json")
        dependencies_resolved = False
        wait_release_source: str | None = None
        wait_satisfied_at: float | None = None
        next_fallback_at = (
            time.monotonic() + _WAIT_DEPENDENCY_FALLBACK_INTERVAL
            if project_name
            else None
        )
        next_bead_hint_at = (
            time.monotonic() + _WAIT_BEAD_HINT_FALLBACK_INTERVAL
            if project_name and wait_beads
            else None
        )
        next_trim_at = time.monotonic() + IDLE_TRIM_INTERVAL_SECONDS
        blocked_since = time.time()
        blocked_since_monotonic = time.monotonic()
        next_handoff_at = blocked_since_monotonic + LEAN_WAIT_HANDOFF_AFTER_SECONDS
        while not dependencies_resolved:
            if os.path.exists(ready_path):
                ready_result = read_ready_result(ready_path)
                if ready_result:
                    dependencies_resolved = True
                    # ``read_ready_result`` may be a stubbed plain bool in
                    # tests; telemetry fields default to absent there.
                    if getattr(ready_result, "unwait", False):
                        wait_release_source = "manual"
                    else:
                        wait_release_source = "ready_json"
                        wait_satisfied_at = getattr(
                            ready_result,
                            "dependencies_satisfied_at",
                            None,
                        )
                    break
            if was_killed():
                break
            now = time.monotonic()
            if lean_wait_handoff is not None and now >= next_handoff_at:
                if lean_wait_handoff("dependency", None, blocked_since):
                    return True
                next_handoff_at = now + LEAN_WAIT_HANDOFF_AFTER_SECONDS
            if next_fallback_at is not None and now >= next_fallback_at:
                if next_bead_hint_at is not None and now >= next_bead_hint_at:
                    mark_bead_wait_sync_hint(project_name)
                    next_bead_hint_at = now + _WAIT_BEAD_HINT_FALLBACK_INTERVAL
                fallback_result = waiting_marker_dependencies_resolved(
                    Path(waiting_path),
                    project_name=project_name,
                    artifacts_dir=artifacts_dir,
                )
                if fallback_result:
                    dependencies_resolved = True
                    wait_release_source = "runner_fallback"
                    wait_satisfied_at = getattr(fallback_result, "satisfied_at", None)
                    print(
                        "Dependencies satisfied by runner fallback "
                        "(ready.json not observed)"
                    )
                    break
                next_fallback_at = now + _WAIT_DEPENDENCY_FALLBACK_INTERVAL
            blocked = True
            # Fallback resolution allocates; release what it leaves behind
            # instead of growing the parked runner again.
            if now >= next_trim_at:
                release_idle_memory()
                next_trim_at = now + IDLE_TRIM_INTERVAL_SECONDS
            time.sleep(_WAIT_READY_POLL_INTERVAL)

        # The dependency-release instant for latency telemetry, captured
        # at loop exit before any post-dependency duration floor starts.
        dependency_released_at = time.time() if dependencies_resolved else None
        if wait_beads:
            # Bead-close times are not observable; stamp no satisfied-at.
            wait_satisfied_at = None

        post_dependency_wait_until = wait_until
        if (
            duration is not None
            and duration > 0
            and dependencies_resolved
            and not was_killed()
        ):
            deadline = datetime.now(UTC) + timedelta(seconds=duration)
            post_dependency_wait_until = deadline.isoformat()
            set_waiting_until(artifacts_dir, post_dependency_wait_until)

        # If a post-dependency time floor is set, sleep until the target.
        if post_dependency_wait_until is not None and not was_killed():
            remaining = remaining_until(post_dependency_wait_until)
            if remaining > 0:
                print(
                    "Dependencies satisfied, waiting until "
                    f"{post_dependency_wait_until}"
                )
                while remaining > 0 and not was_killed():
                    sleep_time = min(_WAIT_TIME_POLL_INTERVAL, remaining)
                    blocked = True
                    time.sleep(sleep_time)
                    remaining = remaining_until(post_dependency_wait_until)

        if not was_killed():
            record_wait_completed_at(
                artifacts_dir,
                agent_meta,
                wait_release_source=wait_release_source,
                wait_dependencies_satisfied_at=wait_satisfied_at,
                wait_released_at=dependency_released_at,
            )

        # Clean up wait markers.
        _remove_wait_markers(artifacts_dir)
    elif wait_until is not None:
        # --- Absolute-time-only path (no agent-name dependencies) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        until_waiting_data: dict[str, Any] = {
            "waiting_for": [],
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_until": wait_until,
        }
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(until_waiting_data, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)

        print(f"Waiting until: {wait_until}")
        remaining = remaining_until(wait_until)
        blocked_since = time.time()
        blocked_since_monotonic = time.monotonic()
        next_handoff_at = blocked_since_monotonic + LEAN_WAIT_HANDOFF_AFTER_SECONDS
        while remaining > 0 and not was_killed():
            now = time.monotonic()
            if lean_wait_handoff is not None and now >= next_handoff_at:
                if lean_wait_handoff("until", time.time() + remaining, blocked_since):
                    return True
                next_handoff_at = now + LEAN_WAIT_HANDOFF_AFTER_SECONDS
            sleep_time = min(_WAIT_TIME_POLL_INTERVAL, remaining)
            blocked = True
            time.sleep(sleep_time)
            remaining = remaining_until(wait_until)

        if not was_killed():
            record_wait_completed_at(
                artifacts_dir, agent_meta, wait_release_source="timer"
            )

        # Clean up waiting.json.
        _remove_wait_markers(artifacts_dir)
    else:
        # --- Duration-only path (no agent-name dependencies) ---
        assert duration is not None

        # Write waiting.json so TUI can detect WAITING status.
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        dur_waiting_data: dict[str, Any] = {
            "waiting_for": [],
            "patch_name": cl_name,
            "cl_name": cl_name,
            "timestamp": timestamp,
            "wait_duration": duration,
        }
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(dur_waiting_data, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)

        print(f"Waiting for duration: {duration:.0f}s")
        remaining = duration
        blocked_since = time.time()
        blocked_since_monotonic = time.monotonic()
        next_handoff_at = blocked_since_monotonic + LEAN_WAIT_HANDOFF_AFTER_SECONDS
        while remaining > 0 and not was_killed():
            now = time.monotonic()
            if (
                lean_wait_handoff is not None
                and remaining >= LEAN_WAIT_HANDOFF_AFTER_SECONDS
                and now >= next_handoff_at
            ):
                if lean_wait_handoff(
                    "duration", time.time() + remaining, blocked_since
                ):
                    return True
                next_handoff_at = now + LEAN_WAIT_HANDOFF_AFTER_SECONDS
            sleep_time = min(_WAIT_TIME_POLL_INTERVAL, remaining)
            blocked = True
            time.sleep(sleep_time)
            remaining -= sleep_time

        if not was_killed():
            record_wait_completed_at(
                artifacts_dir, agent_meta, wait_release_source="timer"
            )

        # Clean up waiting.json.
        _remove_wait_markers(artifacts_dir)

    if was_killed():
        print("Agent killed while waiting", file=sys.stderr)
        sys.exit(128 + 15)  # SIGTERM

    print("All dependencies satisfied, proceeding with workflow")
    return blocked
