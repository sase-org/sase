"""Deep AXE runtime state checks for ``sase doctor``."""

from __future__ import annotations

from typing import Any

from sase.ace.hooks.processes import is_process_running
from sase.axe.config import load_axe_config
from sase.axe.maintenance import read_maintenance
from sase.axe.state import read_lumberjack_status
from sase.diagnostics import CheckStatus, DiagnosticCheck


def check_axe_state() -> DiagnosticCheck:
    """Summarize configured axe/lumberjack runtime state."""
    config = load_axe_config()
    maintenance = read_maintenance()
    rows: list[dict[str, Any]] = []
    problems: list[str] = []

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
            continue

        running = is_process_running(status.pid)
        state = "running" if running else "stale_status"
        if not running:
            problems.append(f"{name}: stale status file for PID {status.pid}")
        if status.errors_encountered:
            problems.append(f"{name}: {status.errors_encountered} error(s) encountered")
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
            }
        )

    if maintenance is not None:
        problems.append(
            f"axe maintenance active: {maintenance.get('reason', 'unknown')}"
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
        next_steps=("Run `sase axe lumberjack status`.",) if problems else (),
        data={
            "lumberjacks": rows,
            "maintenance": maintenance,
            "max_hook_runners": config.max_hook_runners,
            "max_agent_runners": config.max_agent_runners,
            "zombie_timeout_seconds": config.zombie_timeout_seconds,
        },
    )
