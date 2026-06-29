"""Dependency and time-based waiting helpers for the run agent runner."""

import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sase.axe.run_agent_markers import write_agent_meta
from sase.axe.runner_utils import was_killed
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependencies_resolved,
)


def remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    target = dt_cls.fromisoformat(wait_until)
    now = dt_cls.now(target.tzinfo) if target.tzinfo is not None else dt_cls.now()
    return max(0.0, (target - now).total_seconds())


def _write_waiting_marker(
    artifacts_dir: str,
    waiting_data: dict[str, Any],
) -> None:
    waiting_path = os.path.join(artifacts_dir, "waiting.json")
    with open(waiting_path, "w", encoding="utf-8") as f:
        json.dump(waiting_data, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def _record_wait_completed_at(
    artifacts_dir: str,
    agent_meta: dict[str, Any],
) -> str:
    """Persist the wait-barrier completion timestamp."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    disk_meta: dict[str, Any] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            disk_meta = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    disk_wait_completed_at = disk_meta.get("wait_completed_at")
    if isinstance(disk_wait_completed_at, str) and disk_wait_completed_at:
        agent_meta["wait_completed_at"] = disk_wait_completed_at
        return disk_wait_completed_at

    wait_completed_at = datetime.now(UTC).isoformat()
    merged_meta = {**disk_meta, **agent_meta, "wait_completed_at": wait_completed_at}
    agent_meta.update(merged_meta)
    write_agent_meta(artifacts_dir, merged_meta)
    return wait_completed_at


def _all_dependencies_already_resolved(
    wait_names: list[str],
    *,
    project_name: str | None,
) -> bool:
    if not project_name:
        return False

    try:
        dependency_index = build_wait_dependency_index(project_name)
    except Exception:
        return False
    return dependencies_resolved(dependency_index, wait_names)


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    project_name: str | None = None,
    duration: float | None = None,
    wait_until: str | None = None,
) -> None:
    """Wait for named agent dependencies, a duration, or an absolute time.

    When *wait_names* is non-empty, writes waiting.json, polls for ready.json,
    then returns once the agent can proceed.  When *duration* is set alongside
    named dependencies, the duration starts after ready.json appears; without
    named dependencies, the duration starts immediately.  When *wait_until* is
    set (ISO 8601 timestamp), the agent won't start before that wall-clock time.

    Exits with SIGTERM code if killed during wait.
    """
    _WAIT_POLL_INTERVAL = 2  # seconds
    _WAIT_MAX_TIMEOUT = 86400  # 24 hours

    if (
        wait_names
        and duration is None
        and wait_until is None
        and _all_dependencies_already_resolved(
            wait_names,
            project_name=project_name,
        )
    ):
        print("Dependencies already satisfied, proceeding without waiting")
        if not was_killed():
            _record_wait_completed_at(artifacts_dir, agent_meta)
    elif wait_names:
        # --- Agent-name dependency path (with optional duration/time floor) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        waiting_data: dict[str, Any] = {
            "waiting_for": wait_names,
            "cl_name": cl_name,
            "timestamp": timestamp,
        }
        if duration is not None:
            waiting_data["wait_duration"] = duration
        if wait_until is not None:
            waiting_data["wait_until"] = wait_until
        _write_waiting_marker(artifacts_dir, waiting_data)

        parts = [f"agents: {', '.join(wait_names)}"]
        if duration is not None:
            parts.append(f"duration: {duration:.0f}s")
        if wait_until is not None:
            parts.append(f"until: {wait_until}")
        print(f"Waiting for {' and '.join(parts)}")

        # Poll for ready.json (written by wait_checks lumberjack chop).
        ready_path = os.path.join(artifacts_dir, "ready.json")
        wait_elapsed = 0.0
        while not os.path.exists(ready_path):
            if was_killed():
                break
            if wait_elapsed >= _WAIT_MAX_TIMEOUT:
                print(
                    "Wait timeout exceeded, proceeding anyway",
                    file=sys.stderr,
                )
                break
            time.sleep(_WAIT_POLL_INTERVAL)
            wait_elapsed += _WAIT_POLL_INTERVAL

        ready_observed = os.path.exists(ready_path)
        post_dependency_wait_until = wait_until
        if (
            duration is not None
            and duration > 0
            and ready_observed
            and not was_killed()
        ):
            deadline = datetime.now(UTC) + timedelta(seconds=duration)
            post_dependency_wait_until = deadline.isoformat()
            waiting_data["wait_until"] = post_dependency_wait_until
            _write_waiting_marker(artifacts_dir, waiting_data)

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
                    time.sleep(sleep_time)
                    remaining = remaining_until(post_dependency_wait_until)

        if not was_killed():
            _record_wait_completed_at(artifacts_dir, agent_meta)

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
            time.sleep(sleep_time)
            remaining = remaining_until(wait_until)

        if not was_killed():
            _record_wait_completed_at(artifacts_dir, agent_meta)

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
            time.sleep(sleep_time)
            remaining -= sleep_time

        if not was_killed():
            _record_wait_completed_at(artifacts_dir, agent_meta)

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
