"""Axe restart helpers for ``sase update``."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.main.update_types import AxeRunningFn, RestartAxeFn, RestartInfo


def restart_skipped(*, changed: bool) -> RestartInfo:
    if changed:
        return RestartInfo(
            attempted=False,
            status="skipped_not_running",
            reason="axe is not running",
        )
    return RestartInfo(
        attempted=False,
        status="skipped_no_change",
        reason="no code changed",
    )


def restart_after_update(
    *,
    changed: bool,
    axe_running_fn: AxeRunningFn,
    restart_axe_fn: RestartAxeFn,
) -> RestartInfo:
    if not changed:
        return restart_skipped(changed=False)
    try:
        axe_running = axe_running_fn()
    except Exception as exc:  # noqa: BLE001 - update succeeded; report restart only.
        return RestartInfo(
            attempted=False,
            status="failed",
            message=f"could not check axe status: {exc}",
        )
    if not axe_running:
        return restart_skipped(changed=True)

    try:
        result = restart_axe_fn()
    except Exception as exc:  # noqa: BLE001 - keep update success separate.
        return RestartInfo(
            attempted=True,
            status="failed",
            message=f"axe restart failed: {exc}",
        )
    if result.succeeded and result.pid is not None:
        return RestartInfo(
            attempted=True,
            status="restarted",
            pid=result.pid,
            message=f"Axe restarted (pid {result.pid})",
            attempts=result.attempts,
            verified=result.verified,
        )
    return RestartInfo(
        attempted=True,
        status="failed",
        message=result.message or "Failed to restart axe",
        attempts=result.attempts,
        verified=result.verified,
    )


def render_restart_info(restart: RestartInfo, *, console: Console, quiet: bool) -> None:
    if restart.status in ("skipped_no_change", "skipped_not_running"):
        return
    text = Text()
    if restart.status == "restarted":
        text.append("↻ ", style="green")
        text.append(restart.message, style="green")
        text.append(" to load the updated code.", style="dim")
    else:
        text.append("⚠ ", style="yellow")
        text.append(restart.message or "Axe restart failed.", style="yellow")
    console.print(
        text if quiet else Panel(text, title="Axe Restart", border_style="cyan")
    )
