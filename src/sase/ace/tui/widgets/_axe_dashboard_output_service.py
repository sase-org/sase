"""Service-proc detail rendering for the axe dashboard widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.core.time import format_local

from ..util.axe_log_renderer import render_axe_output

if TYPE_CHECKING:
    from sase.service.status import ServiceStatusProc, ServiceStatusSnapshot


def _service_state_style(state: str, desired: str | None = None) -> str:
    """Return a compact display style for a service state token."""
    from .._service_severity import service_proc_style

    return service_proc_style(state, desired)


def _service_host_style(state: str) -> str:
    """Return the display style for a service host state."""
    from .._service_severity import service_host_style

    return service_host_style(state)


def _format_epoch(value: float) -> str:
    """Format a service status epoch timestamp for the detail pane."""
    return format_local(value, default=str(value))


def _service_restart_reason(proc: ServiceStatusProc) -> str | None:
    """Return the restart decision's human reason for a proc row, if any."""
    restart = getattr(proc, "restart", None)
    if isinstance(restart, dict):
        reason = restart.get("reason")
    elif restart is not None:
        reason = getattr(restart, "reason", None)
    else:
        reason = None
    return str(reason) if reason else None


def _service_stop_provenance(proc: ServiceStatusProc) -> str | None:
    """Return ``stopped_by`` plus ``reason`` for a proc row, if any."""
    stop = getattr(proc, "stop", None)
    if stop is None:
        return None
    if isinstance(stop, dict):
        by = stop.get("stopped_by")
        reason = stop.get("reason")
    else:
        by = getattr(stop, "stopped_by", None)
        reason = getattr(stop, "reason", None)
    if not by and not reason:
        return None
    if by and reason:
        return f"{by} ({reason})"
    return str(by or reason)


def _service_pending_request(proc: ServiceStatusProc) -> str | None:
    """Return a one-line pending start/restart request for a proc row, if any."""
    request = getattr(proc, "request", None)
    if request is None:
        return None
    if isinstance(request, dict):
        action = request.get("action", "?")
        generation = request.get("generation", "?")
        completed = request.get("completed_generation")
    else:
        action = getattr(request, "action", "?")
        generation = getattr(request, "generation", "?")
        completed = getattr(request, "completed_generation", None)
    try:
        pending = completed is None or int(completed) < int(generation)
    except (TypeError, ValueError):
        pending = True
    if not pending:
        return None
    return f"{action} #{generation} pending"


class AxeServiceOutputMixin(Static):
    """Mixin providing service-proc detail rendering."""

    _cached_lumberjack_overview: Any
    _cached_lumberjack_overview_layout: Any

    def update_service_proc(
        self,
        *,
        snapshot: ServiceStatusSnapshot | None,
        proc: ServiceStatusProc | None,
        name: str,
        output: str,
    ) -> None:
        """Render selected service-proc details and its bounded output log."""
        self._cached_lumberjack_overview = None
        self._cached_lumberjack_overview_layout = None
        text = Text()
        label = "Scheduler" if name == "scheduler" else name

        text.append("  SERVICE PROC\n", style="bold #00D7AF")
        text.append("  " + "─" * 68 + "\n", style="dim")
        text.append("  ")
        text.append(label, style="bold #00D7AF")
        text.append("\n\n")

        if snapshot is not None:
            text.append("  Host: ", style="bold #87D7FF")
            text.append(
                snapshot.host.summary, style=_service_host_style(snapshot.host.state)
            )
            if snapshot.host.pid is not None:
                text.append("    PID: ", style="bold #87D7FF")
                text.append(str(snapshot.host.pid), style="#FF87D7")
            text.append("\n")
            if snapshot.host.error:
                text.append("  Host error: ", style="bold #87D7FF")
                text.append(snapshot.host.error, style="bold red")
                text.append("\n")

        if proc is None:
            text.append(
                "  Status unavailable for this service proc.", style="dim italic"
            )
            self.update(text)
            return

        rows: list[tuple[str, str, str]] = [
            (
                "State",
                proc.summary or proc.state,
                _service_state_style(proc.state, proc.desired),
            ),
            ("Desired", proc.desired, "#00D7AF"),
            (
                "Enabled",
                proc.enablement.summary,
                "#00D7AF" if proc.enablement.enabled else "dim",
            ),
            ("Source", f"{proc.source} ({proc.declared_by})", "dim"),
            ("Mode", proc.mode, "#87D7FF"),
        ]
        if proc.launcher_summary:
            rows.append(("Launcher", proc.launcher_summary, "#87D7FF"))
        if proc.pid is not None:
            rows.append(("PID", str(proc.pid), "#FF87D7"))
        if proc.started_at is not None:
            rows.append(("Started", _format_epoch(proc.started_at), "#87D7FF"))
        rows.append(("Restarts", str(proc.restarts), "#FFD700"))
        restart_reason = _service_restart_reason(proc)
        if restart_reason:
            rows.append(("Restart", restart_reason, "#FFAF5F"))
        stop_provenance = _service_stop_provenance(proc)
        if stop_provenance:
            rows.append(("Stopped by", stop_provenance, "dim"))
        pending_request = _service_pending_request(proc)
        if pending_request:
            rows.append(("Request", pending_request, "#00D7AF"))
        if proc.log_path:
            rows.append(("Log", proc.log_path, "dim"))

        for key, value, style in rows:
            text.append("  ")
            text.append(f"{key}: ", style="bold #87D7FF")
            text.append(value, style=style)
            text.append("\n")

        if proc.last_exit is not None:
            text.append("\n  LAST EXIT\n", style="bold #00D7AF")
            if proc.last_exit.exit_code is not None:
                text.append("  Exit code: ", style="bold #87D7FF")
                exit_style = "bold red" if proc.last_exit.exit_code else "#00D7AF"
                text.append(str(proc.last_exit.exit_code), style=exit_style)
                text.append("\n")
            if proc.last_exit.signal is not None:
                text.append("  Signal: ", style="bold #87D7FF")
                text.append(str(proc.last_exit.signal), style="bold red")
                text.append("\n")
            if proc.last_exit.spawn_error:
                text.append("  Spawn error: ", style="bold #87D7FF")
                text.append(proc.last_exit.spawn_error, style="bold red")
                text.append("\n")
            if proc.last_exit.finished_at is not None:
                text.append("  Finished: ", style="bold #87D7FF")
                text.append(_format_epoch(proc.last_exit.finished_at), style="#87D7FF")
                text.append("\n")

        if proc.reported is not None:
            text.append("\n  REPORTED\n", style="bold #00D7AF")
            text.append("  ")
            text.append(
                proc.reported.state, style=_service_state_style(proc.reported.state)
            )
            text.append(" — ", style="dim")
            text.append(proc.reported.summary, style="#87D7FF")
            text.append("\n")

        if proc.unavailable_reason:
            text.append("\n  UNAVAILABLE\n", style="bold #FFAF5F")
            text.append(f"  {proc.unavailable_reason}\n", style="#FFAF5F")

        if snapshot is not None and snapshot.diagnostics:
            text.append("\n  DIAGNOSTICS\n", style="bold #FFAF5F")
            for diagnostic in snapshot.diagnostics:
                text.append(f"  {diagnostic}\n", style="#FFAF5F")

        text.append("\n  OUTPUT\n", style="bold #00D7AF")
        text.append("  " + "─" * 68 + "\n", style="dim")
        if output:
            highlighted = render_axe_output(f"service:{name}", output, "ansi")
            lines = highlighted.split(allow_blank=False)
            for line in lines:
                text.append("  ")
                text.append_text(line)
                text.append("\n")
        elif proc.state == "running":
            text.append("  Waiting for output...", style="dim italic")
        else:
            text.append("  No output.", style="dim italic")

        self.update(text)
