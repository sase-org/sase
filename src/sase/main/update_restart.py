"""Scheduler restart helpers for ``sase update``."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.axe.process import is_axe_running
from sase.main.update_types import (
    RestartInfo,
    RestartSchedulerFn,
    SchedulerRunningFn,
)
from sase.service.actions import (
    ServiceProcActionError,
    ServiceProcActionOutcome,
    restart_service_proc,
    wait_for_service_proc_request,
)
from sase.service.config import ServiceConfigError
from sase.service.control import current_service_status

#: How long ``sase update`` waits for the host to confirm a scheduler restart.
_RESTART_CONFIRM_TIMEOUT_SECONDS = 25.0


def restart_skipped(*, changed: bool) -> RestartInfo:
    if changed:
        return RestartInfo(
            attempted=False,
            status="skipped_not_running",
            reason="scheduler is not running",
        )
    return RestartInfo(
        attempted=False,
        status="skipped_no_change",
        reason="no code changed",
    )


def restart_scheduler_service_proc(
    *,
    reason: str | None = None,
) -> ServiceProcActionOutcome:
    """Ask the service host to restart the ``scheduler`` service proc."""
    return restart_service_proc("scheduler", actor="cli", reason=reason)


def restart_after_update(
    *,
    changed: bool,
    scheduler_running_fn: SchedulerRunningFn = is_axe_running,
    restart_scheduler_fn: RestartSchedulerFn = restart_scheduler_service_proc,
    source: str = "sase update",
    timeout: float = _RESTART_CONFIRM_TIMEOUT_SECONDS,
) -> RestartInfo:
    if not changed:
        return restart_skipped(changed=False)
    try:
        scheduler_running = scheduler_running_fn()
    except Exception as exc:  # noqa: BLE001 - update succeeded; report restart only.
        return RestartInfo(
            attempted=False,
            status="failed",
            message=f"could not check scheduler status: {exc}",
        )
    if not scheduler_running:
        return restart_skipped(changed=True)

    old_pid = _current_scheduler_pid()
    try:
        outcome = restart_scheduler_fn(reason=source)
    except (ServiceProcActionError, ServiceConfigError) as exc:
        return RestartInfo(
            attempted=True,
            status="failed",
            message=str(exc),
        )
    return _confirm_scheduler_restart(outcome, old_pid=old_pid, timeout=timeout)


def _current_scheduler_pid() -> int | None:
    try:
        snapshot = current_service_status()
    except Exception:  # noqa: BLE001 - update succeeded; report restart only.
        return None
    row = next((proc for proc in snapshot.procs if proc.name == "scheduler"), None)
    return row.pid if row is not None else None


def _confirm_scheduler_restart(
    outcome: ServiceProcActionOutcome,
    *,
    old_pid: int | None,
    timeout: float,
) -> RestartInfo:
    if outcome.generation is None or not outcome.nudged:
        return RestartInfo(
            attempted=True,
            status="unconfirmed",
            message=outcome.message,
        )
    completed = wait_for_service_proc_request(
        outcome.name, outcome.generation, timeout=timeout
    )
    if completed is None:
        return RestartInfo(
            attempted=True,
            status="unconfirmed",
            message=(
                f"{outcome.message} (generation {outcome.generation}); the service "
                f"host did not confirm within {timeout:g}s"
            ),
        )
    if completed.outcome not in ("restarted", "started", "already_running"):
        return RestartInfo(
            attempted=True,
            status="failed",
            message=completed.error
            or f"scheduler restart reported {completed.outcome!r}",
        )
    if old_pid is not None and completed.pid is not None:
        message = (
            f"service proc scheduler restarted: pid {old_pid} -> pid {completed.pid}"
        )
    else:
        message = outcome.message
    return RestartInfo(
        attempted=True,
        status="restarted",
        message=message,
    )


def render_restart_info(
    restart: RestartInfo,
    *,
    console: Console,
    quiet: bool,
    purpose: str = "load the updated code",
) -> None:
    if restart.status in ("skipped_no_change", "skipped_not_running"):
        return
    text = Text()
    if restart.status == "restarted":
        text.append("↻ ", style="green")
        text.append(restart.message, style="green")
        text.append(f" to {purpose}.", style="dim")
    else:
        text.append("⚠ ", style="yellow")
        text.append(restart.message or "Scheduler restart failed.", style="yellow")
    console.print(
        text if quiet else Panel(text, title="Scheduler Restart", border_style="cyan")
    )
