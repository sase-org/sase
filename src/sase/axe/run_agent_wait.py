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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.axe.run_agent_wait_deps import (
    initial_dependencies_resolved,
    read_ready_result,
    refresh_bead_wait_store,
    waiting_marker_dependencies_resolved,
)
from sase.axe.run_agent_wait_markers import (
    record_wait_completed_at,
    write_waiting_marker,
)
from sase.axe.runner_signals import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)

_WAIT_DEPENDENCY_FALLBACK_INTERVAL = 60.0
_WAIT_BEAD_REFRESH_FALLBACK_INTERVAL = 600.0


def remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    from sase.core.time import local_now

    target = dt_cls.fromisoformat(wait_until)
    now = dt_cls.now(target.tzinfo) if target.tzinfo is not None else local_now()
    return max(0.0, (target - now).total_seconds())


def _opportunistic_ensure_axe() -> None:
    """Best-effort, host-rate-limited healing while waiters are alive."""
    try:
        from sase.axe.ensure import DEFAULT_ENSURE_CADENCE_SECONDS, ensure_axe

        ensure_axe(
            rate_limit_seconds=DEFAULT_ENSURE_CADENCE_SECONDS,
            source="waiting agent runner",
        )
    except Exception:  # noqa: BLE001 - waiting must survive watchdog failures.
        pass


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    project_name: str | None = None,
    wait_identity_deps: list[dict[str, str]] | None = None,
    wait_beads: list[str] | None = None,
    duration: float | None = None,
    wait_until: str | None = None,
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
    _WAIT_POLL_INTERVAL = 2  # seconds

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
    wait_identity_deps = list(wait_identity_deps or [])
    wait_beads = list(wait_beads or [])
    has_dependencies = bool(wait_names or wait_identity_deps or wait_beads)
    dependencies_already_resolved = (
        initial_dependencies_resolved(
            wait_names,
            wait_identity_deps,
            wait_beads=wait_beads,
            project_name=project_name,
            artifacts_dir=artifacts_dir,
        )
        if has_dependencies and duration is None and wait_until is None
        else False
    )

    if (
        has_dependencies
        and duration is None
        and wait_until is None
        and dependencies_already_resolved
    ):
        print("Dependencies already satisfied, proceeding without waiting")
        if not was_killed():
            record_wait_completed_at(artifacts_dir, agent_meta)
        return False
    elif has_dependencies:
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
        if wait_beads:
            waiting_data["wait_for_beads"] = wait_beads
        if duration is not None:
            waiting_data["wait_duration"] = duration
        if wait_until is not None:
            waiting_data["wait_until"] = wait_until
        write_waiting_marker(artifacts_dir, waiting_data)

        parts = []
        if wait_names:
            parts.append(f"agents: {', '.join(wait_names)}")
        if wait_beads:
            parts.append(f"beads: {', '.join(wait_beads)}")
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
        next_fallback_at = (
            time.monotonic() + _WAIT_DEPENDENCY_FALLBACK_INTERVAL
            if project_name
            else None
        )
        next_bead_refresh_at = (
            time.monotonic() + _WAIT_BEAD_REFRESH_FALLBACK_INTERVAL
            if project_name and wait_beads
            else None
        )
        while not dependencies_resolved:
            if os.path.exists(ready_path):
                dependencies_resolved = read_ready_result(ready_path)
                if dependencies_resolved:
                    break
            if was_killed():
                break
            now = time.monotonic()
            if next_fallback_at is not None and now >= next_fallback_at:
                if next_bead_refresh_at is not None and now >= next_bead_refresh_at:
                    refresh_bead_wait_store(project_name)
                    next_bead_refresh_at = now + _WAIT_BEAD_REFRESH_FALLBACK_INTERVAL
                if waiting_marker_dependencies_resolved(
                    Path(waiting_path),
                    project_name=project_name,
                    artifacts_dir=artifacts_dir,
                ):
                    dependencies_resolved = True
                    print(
                        "Dependencies satisfied by runner fallback "
                        "(ready.json not observed)"
                    )
                    break
                next_fallback_at = now + _WAIT_DEPENDENCY_FALLBACK_INTERVAL
            blocked = True
            _opportunistic_ensure_axe()
            time.sleep(_WAIT_POLL_INTERVAL)

        post_dependency_wait_until = wait_until
        if (
            duration is not None
            and duration > 0
            and dependencies_resolved
            and not was_killed()
        ):
            deadline = datetime.now(UTC) + timedelta(seconds=duration)
            post_dependency_wait_until = deadline.isoformat()
            waiting_data["wait_until"] = post_dependency_wait_until
            write_waiting_marker(artifacts_dir, waiting_data)

        # If a post-dependency time floor is set, sleep until the target.
        if post_dependency_wait_until is not None and not was_killed():
            remaining = remaining_until(post_dependency_wait_until)
            if remaining > 0:
                print(
                    "Dependencies satisfied, waiting until "
                    f"{post_dependency_wait_until}"
                )
                while remaining > 0 and not was_killed():
                    sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
                    blocked = True
                    time.sleep(sleep_time)
                    remaining = remaining_until(post_dependency_wait_until)

        if not was_killed():
            record_wait_completed_at(artifacts_dir, agent_meta)

        # Clean up wait markers.
        for path in (waiting_path, ready_path):
            try:
                os.unlink(path)
                if path == waiting_path:
                    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
            except OSError:
                pass
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
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            blocked = True
            time.sleep(sleep_time)
            remaining = remaining_until(wait_until)

        if not was_killed():
            record_wait_completed_at(artifacts_dir, agent_meta)

        # Clean up waiting.json.
        try:
            os.unlink(waiting_path)
            update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        except OSError:
            pass
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
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            blocked = True
            time.sleep(sleep_time)
            remaining -= sleep_time

        if not was_killed():
            record_wait_completed_at(artifacts_dir, agent_meta)

        # Clean up waiting.json.
        try:
            os.unlink(waiting_path)
            update_agent_artifact_index_for_marker_mutation(artifacts_dir)
        except OSError:
            pass

    if was_killed():
        print("Agent killed while waiting", file=sys.stderr)
        sys.exit(128 + 15)  # SIGTERM

    print("All dependencies satisfied, proceeding with workflow")
    return blocked
