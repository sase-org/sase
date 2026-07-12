"""Dependency and time-based waiting helpers for the run agent runner."""

import fcntl
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.agent.names import is_process_alive
from sase.axe.run_agent_markers import write_agent_meta
from sase.axe.runner_utils import was_killed
from sase.config.core import get_max_running_agents
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.runner_slots import (
    live_runner_slot_waiters,
    may_start,
    running_root_agent_count,
)
from sase.core.wait_dependency_resolution import (
    build_wait_dependency_index,
    dependency_resolution_status,
)


def remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    from sase.core.time import local_now

    target = dt_cls.fromisoformat(wait_until)
    now = dt_cls.now(target.tzinfo) if target.tzinfo is not None else local_now()
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


def _initial_dependencies_resolved(
    wait_names: list[str],
    wait_identity_deps: list[dict[str, str]],
    *,
    project_name: str | None,
    artifacts_dir: str,
) -> bool:
    if not project_name:
        return False

    try:
        dependency_index = build_wait_dependency_index(project_name)
    except Exception:
        return False
    status = dependency_resolution_status(
        dependency_index,
        wait_names,
        wait_identity_deps,
        self_artifact_dir=artifacts_dir,
    )
    return status.resolved


def _read_ready_result(ready_path: str) -> bool:
    """Return whether a ready marker resolves the wait.

    Cancellation markers written by older SASE versions are stale state. Remove
    them and keep waiting for an actual successful resolution marker.
    """
    try:
        with open(ready_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return True
    if not isinstance(data, dict) or not data.get("cancelled"):
        return True
    try:
        os.unlink(ready_path)
    except OSError:
        pass
    return False


_RUNNER_SLOT_POLL_INTERVAL = 2
_RUNNER_SLOT_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    include_raw_prompt_snippets=False,
    only_workflow_dirs=("ace-run",),
    include_done_markers=False,
)


def _runner_slot_lock_path() -> Path:
    return sase_home() / "runner_slots.lock"


def _scan_runner_slot_records() -> list[AgentArtifactRecordWire]:
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(sase_projects_dir(), _RUNNER_SLOT_SCAN_OPTIONS).records


def _record_liveness_probe() -> Callable[[AgentArtifactRecordWire], bool]:
    cache: dict[str, bool] = {}

    def is_live(record: AgentArtifactRecordWire) -> bool:
        if record.artifact_dir in cache:
            return cache[record.artifact_dir]
        meta = record.agent_meta
        pid = None if meta is None else meta.pid
        if pid is None and record.running is not None:
            pid = record.running.pid
        alive = is_process_alive(
            {
                "pid": pid,
                "stopped_at": None if meta is None else meta.stopped_at,
            },
            Path(record.artifact_dir),
        )
        cache[record.artifact_dir] = alive
        return alive

    return is_live


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
    return value if isinstance(value, dict) else None


def _marker_threshold(
    waiting_data: dict[str, Any] | None,
    directive_threshold: int | None,
) -> tuple[int, bool]:
    if waiting_data is not None and "slot_requested_at" in waiting_data:
        explicit = waiting_data.get("wait_runners_explicit") is True
        marker_value = waiting_data.get("wait_runners")
        if explicit and type(marker_value) is int and marker_value >= 0:
            return marker_value, True
        if not explicit:
            return get_max_running_agents() - 1, False
    if directive_threshold is not None:
        return directive_threshold, True
    return get_max_running_agents() - 1, False


def _remove_waiting_marker(artifacts_dir: str) -> None:
    try:
        os.unlink(os.path.join(artifacts_dir, "waiting.json"))
    except FileNotFoundError:
        return
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def _try_claim_runner_slot(
    *,
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    directive_threshold: int | None,
    claim: Callable[[], str],
) -> tuple[str | None, bool]:
    """Try one check-and-claim under the global lock.

    Returns ``(run_started_at, parked)``. ``parked`` is true when this call
    first published the slot queue marker.
    """
    lock_path = _runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            waiting_path = Path(artifacts_dir) / "waiting.json"
            waiting_data = _read_json_dict(waiting_path)
            threshold, explicit = _marker_threshold(waiting_data, directive_threshold)
            records = _scan_runner_slot_records()
            is_live = _record_liveness_probe()
            queue = live_runner_slot_waiters(records, is_live)
            running_count = running_root_agent_count(records, is_live)
            if may_start(running_count, threshold, queue, artifacts_dir):
                run_started_at = claim()
                _remove_waiting_marker(artifacts_dir)
                return run_started_at, False

            requested_at = (
                waiting_data.get("slot_requested_at")
                if waiting_data is not None
                else None
            )
            if not isinstance(requested_at, str) or not requested_at:
                requested_at = datetime.now(UTC).isoformat()
            marker: dict[str, Any] = {
                "waiting_for": [],
                "cl_name": cl_name,
                "timestamp": timestamp,
                "wait_runners": threshold,
                "wait_runners_explicit": explicit,
                "slot_requested_at": requested_at,
            }
            parked = waiting_data is None or "slot_requested_at" not in waiting_data
            if waiting_data != marker:
                _write_waiting_marker(artifacts_dir, marker)
            return None, parked
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def wait_for_runner_slot(
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    wait_runners: int | None,
    claim: Callable[[], str],
) -> str:
    """Pass the final root-agent runner-slot gate and atomically claim RUNNING.

    Child/follow-up agents are exempt so a parent waiting on its children can
    never deadlock while holding a slot.
    """
    if agent_meta.get("parent_timestamp"):
        return claim()

    while not was_killed():
        run_started_at, parked = _try_claim_runner_slot(
            artifacts_dir=artifacts_dir,
            cl_name=cl_name,
            timestamp=timestamp,
            directive_threshold=wait_runners,
            claim=claim,
        )
        if run_started_at is not None:
            return run_started_at
        if parked:
            print("Waiting for a runner slot")
        time.sleep(_RUNNER_SLOT_POLL_INTERVAL)

    lock_path = _runner_slot_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            _remove_waiting_marker(artifacts_dir)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    print("Agent killed while waiting for a runner slot", file=sys.stderr)
    sys.exit(128 + 15)


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    project_name: str | None = None,
    wait_identity_deps: list[dict[str, str]] | None = None,
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

    wait_identity_deps = list(wait_identity_deps or [])
    has_agent_dependencies = bool(wait_names or wait_identity_deps)
    dependencies_already_resolved = (
        _initial_dependencies_resolved(
            wait_names,
            wait_identity_deps,
            project_name=project_name,
            artifacts_dir=artifacts_dir,
        )
        if has_agent_dependencies and duration is None and wait_until is None
        else False
    )

    if (
        has_agent_dependencies
        and duration is None
        and wait_until is None
        and dependencies_already_resolved
    ):
        print("Dependencies already satisfied, proceeding without waiting")
        if not was_killed():
            _record_wait_completed_at(artifacts_dir, agent_meta)
        return
    elif has_agent_dependencies:
        # --- Agent-name dependency path (with optional duration/time floor) ---
        waiting_path = os.path.join(artifacts_dir, "waiting.json")
        waiting_data: dict[str, Any] = {
            "waiting_for": wait_names,
            "cl_name": cl_name,
            "timestamp": timestamp,
        }
        if wait_identity_deps:
            waiting_data["wait_for_artifacts"] = wait_identity_deps
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
        ready_observed = False
        while not ready_observed:
            if os.path.exists(ready_path):
                ready_observed = _read_ready_result(ready_path)
                if ready_observed:
                    break
            if was_killed():
                break
            time.sleep(_WAIT_POLL_INTERVAL)

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
