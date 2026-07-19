"""Deep AXE runtime state checks for ``sase doctor``."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sase.axe.state as _state

from sase.ace.hooks.processes import is_process_running
from sase.axe.config import DEFAULT_LUMBERJACK_LOG_MAX_BYTES, load_axe_config
from sase.axe.desired_state import read_desired_state
from sase.axe.maintenance import read_maintenance
from sase.axe.state import read_lumberjack_status
from sase.axe._process_probe import probe_orchestrator
from sase.diagnostics import CheckStatus, DiagnosticCheck


_MIN_HEARTBEAT_STALE_SECONDS = 60
_ORPHAN_TEMP_WARN_BYTES = 100 * 1024 * 1024
_ORPHAN_TEMP_WARN_COUNT = 10


def check_axe_state() -> DiagnosticCheck:
    """Summarize configured axe/lumberjack runtime state."""
    config = load_axe_config()
    maintenance = read_maintenance()
    desired = read_desired_state()
    orchestrator_pid = probe_orchestrator(cleanup=False).running_pid
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

    if desired is not None and desired.state == "running" and orchestrator_pid is None:
        problems.append("desired state is running, but the orchestrator is down")

    for name in sorted(config.lumberjacks):
        status = read_lumberjack_status(name)
        if status is None:
            rows.append(
                {
                    "name": name,
                    "configured": True,
                    "state": "not_running",
                    "pid": None,
                    "cycles_run": 0,
                    "errors_encountered": 0,
                }
            )
            if orchestrator_pid is not None:
                problems.append(f"{name}: no lumberjack heartbeat is available")
            continue

        running = is_process_running(status.pid)
        state = "running" if running else "stale_status"
        if not running:
            problems.append(f"{name}: stale status file for PID {status.pid}")
        if status.errors_encountered:
            problems.append(f"{name}: {status.errors_encountered} error(s) encountered")
        heartbeat_age = _timestamp_age_seconds(status.last_cycle, now=now)
        started_age = _timestamp_age_seconds(status.started_at, now=now)
        stale_after = max(_MIN_HEARTBEAT_STALE_SECONDS, status.interval * 3)
        heartbeat_stale = False
        if running and heartbeat_age is not None and heartbeat_age > stale_after:
            heartbeat_stale = True
            problems.append(
                f"{name}: heartbeat is stale ({int(heartbeat_age)}s old; "
                f"expected within {stale_after}s)"
            )
        elif (
            running
            and heartbeat_age is None
            and (started_age is not None and started_age > stale_after)
        ):
            heartbeat_stale = True
            problems.append(
                f"{name}: no heartbeat after {int(started_age)}s "
                f"(expected within {stale_after}s)"
            )
        rows.append(
            {
                "name": name,
                "configured": True,
                "state": state,
                "pid": status.pid,
                "started_at": status.started_at,
                "interval": status.interval,
                "chops": list(status.chops),
                "cycles_run": status.cycles_run,
                "errors_encountered": status.errors_encountered,
                "uptime_seconds": status.uptime_seconds,
                "heartbeat_age_seconds": heartbeat_age,
                "heartbeat_stale": heartbeat_stale,
            }
        )

    if maintenance is not None:
        problems.append(
            f"axe maintenance active: {maintenance.get('reason', 'unknown')}"
        )

    log_cap = int(
        getattr(config, "lumberjack_log_max_bytes", DEFAULT_LUMBERJACK_LOG_MAX_BYTES)
    )
    pinned_logs = _pinned_log_paths(_state.AXE_STATE_DIR, max_bytes=log_cap)
    if pinned_logs:
        problems.append(
            f"{len(pinned_logs)} axe log(s) are pinned at the {log_cap}-byte cap"
        )

    orphan_temp_count, orphan_temp_bytes = _orphan_temp_litter(_state.AXE_STATE_DIR)
    orphan_litter_excessive = (
        orphan_temp_count >= _ORPHAN_TEMP_WARN_COUNT
        or orphan_temp_bytes >= _ORPHAN_TEMP_WARN_BYTES
    )
    if orphan_litter_excessive:
        problems.append(
            f"orphan log-rotation temp litter: {orphan_temp_count} file(s), "
            f"{orphan_temp_bytes} bytes"
        )

    running_count = sum(1 for row in rows if row["state"] == "running")
    status_value: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(rows)} configured lumberjack(s); {running_count} running"
        if rows
        else "no axe lumberjacks are configured"
    )

    return DiagnosticCheck(
        id="ops.axe",
        group="ops",
        status=status_value,
        title="Axe runtime state",
        summary=summary,
        details=tuple(problems[:8]),
        next_steps=(
            (
                "Run `sase axe ensure`, then `sase axe lumberjack status`."
                if orchestrator_pid is None
                else "Run `sase axe lumberjack status`."
            ),
        )
        if problems
        else (),
        data={
            "desired_state": desired.state if desired is not None else None,
            "orchestrator_pid": orchestrator_pid,
            "lumberjacks": rows,
            "pinned_logs": [str(path) for path in pinned_logs],
            "orphan_log_temp_bytes": orphan_temp_bytes,
            "orphan_log_temp_count": orphan_temp_count,
            "maintenance": maintenance,
            "max_hook_runners": config.max_hook_runners,
            "max_agent_runners": config.max_agent_runners,
            "zombie_timeout_seconds": config.zombie_timeout_seconds,
        },
    )


def _timestamp_age_seconds(value: str | None, *, now: datetime) -> float | None:
    if not value:
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return max(0.0, (now - timestamp.astimezone(UTC)).total_seconds())


def _pinned_log_paths(root: Path, *, max_bytes: int) -> tuple[Path, ...]:
    if max_bytes <= 0:
        return ()
    pinned: list[Path] = []
    try:
        candidates = root.rglob("*.log")
        for candidate in candidates:
            try:
                if candidate.stat().st_size >= max_bytes:
                    pinned.append(candidate)
            except OSError:
                continue
    except OSError:
        return ()
    return tuple(sorted(pinned))


def _orphan_temp_litter(root: Path) -> tuple[int, int]:
    count = 0
    total_bytes = 0

    def ignore_walk_error(_error: OSError) -> None:
        return

    for directory, _subdirs, filenames in os.walk(root, onerror=ignore_walk_error):
        for filename in filenames:
            if not (
                filename.startswith(".")
                and ".log." in filename
                and filename.endswith(".tmp")
            ):
                continue
            try:
                total_bytes += (Path(directory) / filename).stat().st_size
                count += 1
            except OSError:
                continue
    return count, total_bytes
