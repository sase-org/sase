"""Deep AXE runtime state checks for ``sase doctor``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import sase.axe.state as _state

from sase.axe.config import DEFAULT_LUMBERJACK_LOG_MAX_BYTES, load_axe_config
from sase.axe.status_collector import collect_axe_status_snapshot
from sase.axe.status_models import (
    AxeLumberjackStatus,
    AxeStatusIssue,
    AxeStatusSnapshot,
)
from sase.diagnostics import CheckStatus, DiagnosticCheck


_ORPHAN_TEMP_WARN_BYTES = 100 * 1024 * 1024
_ORPHAN_TEMP_WARN_COUNT = 10
_MAX_DETAILS = 8
_MAX_NEXT_STEPS = 5


def check_axe_state() -> DiagnosticCheck:
    """Summarize configured axe/lumberjack runtime state."""
    snapshot = collect_axe_status_snapshot()
    rows = [_lumberjack_data(row) for row in snapshot.lumberjacks]
    problems = [issue.summary for issue in snapshot.issues]
    next_steps: list[str] = []
    for issue in snapshot.issues:
        if issue.suggested_command is not None:
            _append_unique(next_steps, _command_next_step(issue))

    historical_errors = [
        row for row in snapshot.lumberjacks if row.errors_encountered > 0
    ]
    for row in historical_errors:
        _append_unique(
            problems,
            f"{row.name}: {row.errors_encountered} cumulative historical error(s)",
        )

    deep_config = _load_deep_config()
    log_cap = int(
        getattr(
            deep_config,
            "lumberjack_log_max_bytes",
            DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
        )
    )
    state_dir = _state.axe_state_dir()
    pinned_logs = _pinned_log_paths(state_dir, max_bytes=log_cap)
    if pinned_logs:
        _append_unique(
            problems,
            f"{len(pinned_logs)} AXE log(s) are pinned at the {log_cap}-byte cap",
        )

    orphan_temp_count, orphan_temp_bytes = _orphan_temp_litter(state_dir)
    orphan_litter_excessive = (
        orphan_temp_count >= _ORPHAN_TEMP_WARN_COUNT
        or orphan_temp_bytes >= _ORPHAN_TEMP_WARN_BYTES
    )
    if orphan_litter_excessive:
        _append_unique(
            problems,
            "orphan log-rotation temp litter: "
            f"{orphan_temp_count} file(s), {orphan_temp_bytes} bytes",
        )

    if historical_errors or pinned_logs or orphan_litter_excessive:
        _append_unique(
            next_steps,
            "Run `sase axe lumberjack status`.",
        )

    configured_count = sum(1 for row in snapshot.lumberjacks if row.configured)
    running_count = sum(
        1 for row in snapshot.lumberjacks if row.configured and row.state == "running"
    )
    status_value = _doctor_status(snapshot, has_deep_findings=bool(problems))
    runtime_summary = (
        f"{configured_count} configured lumberjack(s); {running_count} running"
        if configured_count
        else "no AXE lumberjacks are configured"
    )
    summary = f"{snapshot.summary} {runtime_summary}."
    orchestrator_pid = (
        snapshot.orchestrator.live_pids[0] if snapshot.orchestrator.live_pids else None
    )
    return DiagnosticCheck(
        id="ops.axe",
        group="ops",
        status=status_value,
        title="Axe runtime state",
        summary=summary,
        details=tuple(problems[:_MAX_DETAILS]),
        next_steps=tuple(next_steps[:_MAX_NEXT_STEPS]),
        data={
            "state": snapshot.state,
            "health": snapshot.health,
            "issues": [issue.to_wire() for issue in snapshot.issues],
            "desired_state": (
                snapshot.desired_state.state
                if snapshot.desired_state is not None
                else None
            ),
            "orchestrator_pid": orchestrator_pid,
            "orchestrator_pids": list(snapshot.orchestrator.live_pids),
            "orchestrator_state": snapshot.orchestrator.state,
            "orchestrator_coherence": snapshot.orchestrator.coherence,
            "lumberjacks": rows,
            "pinned_logs": [str(path) for path in pinned_logs],
            "orphan_log_temp_bytes": orphan_temp_bytes,
            "orphan_log_temp_count": orphan_temp_count,
            "maintenance": (
                snapshot.maintenance.to_wire()
                if snapshot.maintenance is not None
                else None
            ),
            "hook_runners": snapshot.hook_runners.to_wire(),
            "agent_runners": snapshot.agent_runners.to_wire(),
            "max_hook_runners": snapshot.hook_runners.maximum,
            "max_agent_runners": snapshot.agent_runners.maximum,
            "zombie_timeout_seconds": getattr(
                deep_config, "zombie_timeout_seconds", None
            ),
            "collection_error": (
                snapshot.collection_error.to_wire()
                if snapshot.collection_error is not None
                else None
            ),
        },
    )


def _doctor_status(
    snapshot: AxeStatusSnapshot,
    *,
    has_deep_findings: bool,
) -> CheckStatus:
    if snapshot.health == "error" or snapshot.collection_error is not None:
        return "ERROR"
    if snapshot.health == "unhealthy" or has_deep_findings:
        return "WARN"
    return "OK"


def _load_deep_config() -> Any | None:
    try:
        return load_axe_config()
    except Exception:  # noqa: BLE001 - snapshot already reports config failure.
        return None


def _lumberjack_data(row: AxeLumberjackStatus) -> dict[str, Any]:
    return {
        "name": row.name,
        "configured": row.configured,
        "state": row.state,
        "pid": row.recorded_pid,
        "recorded_pid": row.recorded_pid,
        "reported_state": row.reported_state,
        "process_live": row.process_live,
        "started_at": row.started_at,
        "interval": row.interval_seconds,
        "interval_seconds": row.interval_seconds,
        "chops": list(row.configured_chops),
        "configured_chops": list(row.configured_chops),
        "cycles_run": row.cycles_run,
        "errors_encountered": row.errors_encountered,
        "uptime_seconds": row.uptime_seconds,
        "heartbeat_at": row.heartbeat_at,
        "heartbeat_age_seconds": row.heartbeat_age_seconds,
        "heartbeat_stale": row.state == "stale_heartbeat",
        "stale_threshold_seconds": row.stale_threshold_seconds,
    }


def _command_next_step(issue: AxeStatusIssue) -> str:
    return f"Run `{issue.suggested_command}`."


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


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
