"""Dependency and time-based waiting helpers for the run agent runner."""

import json
import os
import sys
import time
from typing import Any

from sase.axe.runner_utils import was_killed


def _remaining_until(wait_until: str) -> float:
    """Seconds remaining until the ISO 8601 target time."""
    from datetime import datetime as dt_cls

    target = dt_cls.fromisoformat(wait_until)
    return max(0.0, (target - dt_cls.now()).total_seconds())


def wait_for_dependencies(
    wait_names: list[str],
    artifacts_dir: str,
    cl_name: str,
    timestamp: str,
    agent_meta: dict[str, Any],
    *,
    duration: float | None = None,
    wait_until: str | None = None,
) -> None:
    """Wait for named agent dependencies, a duration, or an absolute time.

    When *wait_names* is non-empty, writes waiting.json, polls for ready.json,
    then returns once the agent can proceed.  When *duration* is set, the agent
    won't start before that many seconds have elapsed — even if all named
    dependencies finish earlier.  When *wait_until* is set (ISO 8601 timestamp),
    the agent won't start before that wall-clock time.

    Exits with SIGTERM code if killed during wait.
    """
    _WAIT_POLL_INTERVAL = 2  # seconds
    _WAIT_MAX_TIMEOUT = 86400  # 24 hours

    if wait_names:
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
        with open(waiting_path, "w", encoding="utf-8") as f:
            json.dump(waiting_data, f, indent=2)

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

        # If a duration floor is set and we finished early, sleep the remainder.
        if duration is not None and wait_elapsed < duration and not was_killed():
            remaining = duration - wait_elapsed
            print(
                f"Dependencies satisfied, sleeping {remaining:.0f}s for duration floor"
            )
            while remaining > 0 and not was_killed():
                sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
                time.sleep(sleep_time)
                remaining -= sleep_time

        # If an absolute-time floor is set, sleep until the target.
        if wait_until is not None and not was_killed():
            remaining = _remaining_until(wait_until)
            if remaining > 0:
                print(f"Dependencies satisfied, waiting until {wait_until}")
                while remaining > 0 and not was_killed():
                    sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
                    time.sleep(sleep_time)
                    remaining = _remaining_until(wait_until)

        # Clean up wait markers.
        for path in (waiting_path, ready_path):
            try:
                os.unlink(path)
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

        print(f"Waiting until: {wait_until}")
        remaining = _remaining_until(wait_until)
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            time.sleep(sleep_time)
            remaining = _remaining_until(wait_until)

        # Clean up waiting.json.
        try:
            os.unlink(waiting_path)
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

        print(f"Waiting for duration: {duration:.0f}s")
        remaining = duration
        while remaining > 0 and not was_killed():
            sleep_time = min(_WAIT_POLL_INTERVAL, remaining)
            time.sleep(sleep_time)
            remaining -= sleep_time

        # Clean up waiting.json.
        try:
            os.unlink(waiting_path)
        except OSError:
            pass

    if was_killed():
        print("Agent killed while waiting", file=sys.stderr)
        sys.exit(128 + 15)  # SIGTERM

    print("All dependencies satisfied, proceeding with workflow")
