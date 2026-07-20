"""Compact status-bar section for the axe dashboard widget."""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.axe.state import AxeStatus, LumberjackStatus

from ._axe_dashboard_render import (
    CHOP_NAME_STYLE as _CHOP_NAME_STYLE,
    LJ_NAME_STYLE as _LJ_NAME_STYLE,
    chop_status_label as _chop_status_label,
    format_duration_ms as _format_duration_ms,
    format_elapsed as _format_elapsed,
    format_runtime as _format_runtime,
    format_time_with_relative as _format_time_with_relative,
)

if TYPE_CHECKING:
    from ..actions.axe_display._data import AxeStatusDegradation, ChopRunSnapshot
    from ..bgcmd import BackgroundCommandInfo


class AxeStatusSection(Static):
    """Compact status bar showing runtime, cycles, and runners."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the status section."""
        super().__init__(**kwargs)
        # State for axe daemon mode
        self._axe_mode = True
        self._status: AxeStatus | None = None
        self._is_running = False
        self._full_cycles = 0
        self._degraded_status: AxeStatusDegradation | None = None
        # State for bgcmd mode
        self._bgcmd_info: BackgroundCommandInfo | None = None
        self._bgcmd_running = False
        # State for lumberjack mode
        self._lumberjack_mode = False
        self._lumberjack_status: LumberjackStatus | None = None
        self._lumberjack_name: str = ""
        self._lumberjack_idx: int = 0
        self._lumberjack_total: int = 0
        # State for chop-run mode (Phase 4 chop detail header)
        self._chop_mode = False
        self._chop_lumberjack_name: str = ""
        self._chop_name: str = ""
        self._chop_run: ChopRunSnapshot | None = None
        self._chop_run_idx: int = 0
        self._chop_run_total: int = 0
        # Shared state
        self._countdown = 0

    def update_display(
        self,
        status: AxeStatus | None,
        is_running: bool,
        full_cycles: int,
        countdown: int = 0,
        degraded_status: "AxeStatusDegradation | None" = None,
    ) -> None:
        """Update the compact status section for axe daemon.

        Args:
            status: Current axe status, or None if not available.
            is_running: Whether axe daemon is currently running.
            full_cycles: Number of full cycles run.
            countdown: Seconds until next auto-refresh.
            degraded_status: Recoverable collection problem to display.
        """
        self._axe_mode = True
        self._lumberjack_mode = False
        self._status = status
        self._is_running = is_running
        self._full_cycles = full_cycles
        self._countdown = countdown
        self._degraded_status = degraded_status
        self._refresh_display()

    def update_bgcmd_display(
        self,
        info: "BackgroundCommandInfo | None",
        is_running: bool,
        countdown: int = 0,
    ) -> None:
        """Update the status section for a background command.

        Args:
            info: Background command info, or None if not available.
            is_running: Whether the command is still running.
            countdown: Seconds until next auto-refresh.
        """
        self._axe_mode = False
        self._lumberjack_mode = False
        self._bgcmd_info = info
        self._bgcmd_running = is_running
        self._countdown = countdown
        self._refresh_display()

    def update_lumberjack_display(
        self,
        status: LumberjackStatus | None,
        name: str,
        idx: int,
        total: int,
        countdown: int = 0,
    ) -> None:
        """Update the status section for a specific lumberjack.

        Args:
            status: Lumberjack status, or None if not available.
            name: Lumberjack name.
            idx: Current index (0-based).
            total: Total number of lumberjacks.
            countdown: Seconds until next auto-refresh.
        """
        self._lumberjack_mode = True
        self._chop_mode = False
        self._axe_mode = False
        self._lumberjack_status = status
        self._lumberjack_name = name
        self._lumberjack_idx = idx
        self._lumberjack_total = total
        self._countdown = countdown
        self._refresh_display()

    def update_chop_display(
        self,
        lumberjack_name: str,
        chop_name: str,
        run: "ChopRunSnapshot | None",
        run_idx: int,
        run_total: int,
        countdown: int = 0,
    ) -> None:
        """Update the status section header for a chop's selected run.

        Args:
            lumberjack_name: Parent lumberjack name.
            chop_name: Chop name.
            run: The selected run snapshot, or None when no runs recorded.
            run_idx: 0-based index of the displayed run within history
                (0 = newest).
            run_total: Total number of runs in cached history.
            countdown: Seconds until next auto-refresh.
        """
        self._chop_mode = True
        self._lumberjack_mode = False
        self._axe_mode = False
        self._chop_lumberjack_name = lumberjack_name
        self._chop_name = chop_name
        self._chop_run = run
        self._chop_run_idx = run_idx
        self._chop_run_total = run_total
        self._countdown = countdown
        self._refresh_display()

    def update_countdown(self, countdown: int) -> None:
        """Update just the countdown display.

        This is called every second by the countdown tick handler.

        Args:
            countdown: Seconds until next auto-refresh.
        """
        self._countdown = countdown
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the display based on current state."""
        if self._chop_mode:
            self._render_chop_display()
        elif self._lumberjack_mode:
            self._render_lumberjack_display()
        elif self._axe_mode:
            self._render_axe_display()
        else:
            self._render_bgcmd_display()

    def _render_axe_display(self) -> None:
        """Render the axe daemon status display."""
        text = Text(no_wrap=True, overflow="ellipsis")

        if self._degraded_status is not None:
            text.append(self._degraded_status.message, style="bold red")
            if self._countdown > 0:
                text.append("  │  ", style="dim")
                text.append("(auto-refresh in ", style="dim")
                text.append(f"{self._countdown}s", style="bold #FFD700")
                text.append(")", style="dim")
            self.update(text)
            return

        if self._is_running:
            # Runtime (always show when running)
            text.append("Runtime: ", style="bold #87D7FF")
            if self._status and self._status.started_at:
                runtime_str = _format_runtime(self._status.started_at)
            else:
                runtime_str = "..."
            text.append(runtime_str, style="#00D7AF")

            # Cycles
            text.append("  │  ", style="dim")
            text.append("Cycles: ", style="bold #87D7FF")
            text.append(f"{self._full_cycles}", style="#00D7AF bold")

            # Hook runners (current/max)
            text.append("  │  ", style="dim")
            text.append("Hooks: ", style="bold #87D7FF")
            if self._status:
                text.append(
                    f"({self._status.current_hook_runners}/{self._status.max_hook_runners})",
                    style="#00D7AF",
                )
            else:
                text.append("...", style="#00D7AF")

            # Agent runners (current/max)
            text.append("  │  ", style="dim")
            text.append("Agents: ", style="bold #87D7FF")
            if self._status:
                text.append(
                    f"({self._status.current_agent_runners}/{self._status.max_agent_runners})",
                    style="#00D7AF",
                )
            else:
                text.append("...", style="#00D7AF")

            # Countdown
            if self._countdown > 0:
                text.append("  │  ", style="dim")
                text.append("(auto-refresh in ", style="dim")
                text.append(f"{self._countdown}s", style="bold #FFD700")
                text.append(")", style="dim")

        self.update(text)

    def _render_bgcmd_display(self) -> None:
        """Render the background command status display."""
        text = Text(no_wrap=True, overflow="ellipsis")
        info = self._bgcmd_info

        if info:
            # Status indicator
            if self._bgcmd_running:
                text.append("[RUNNING]", style="bold green")
            else:
                text.append("[DONE]", style="bold #FFD700")  # Gold/yellow

            # PID
            text.append("  │  ", style="dim")
            text.append("PID: ", style="bold #87D7FF")
            if info.pid:
                text.append(f"{info.pid}", style="#FF87D7 bold")
            else:
                text.append("...", style="#FF87D7 bold")

            # Command
            text.append("  │  ", style="dim")
            text.append("Cmd: ", style="bold #87D7FF")
            cmd_display = info.command
            if len(cmd_display) > 40:
                cmd_display = cmd_display[:37] + "..."
            text.append(cmd_display, style="#FF87D7")

            # Project
            text.append("  │  ", style="dim")
            text.append("Project: ", style="bold #87D7FF")
            text.append(info.display_project, style="#00D7AF")

            # Workspace
            text.append("  │  ", style="dim")
            text.append("WS: ", style="bold #87D7FF")
            text.append(f"{info.workspace_num}", style="#00D7AF")

            # Runtime - use finished_at for done commands
            text.append("  │  ", style="dim")
            text.append("Runtime: ", style="bold #87D7FF")
            runtime_str = _format_elapsed(info.started_at, info.finished_at)
            text.append(runtime_str, style="#00D7AF")

            # Countdown
            if self._countdown > 0:
                text.append("  │  ", style="dim")
                text.append("(auto-refresh in ", style="dim")
                text.append(f"{self._countdown}s", style="bold #FFD700")
                text.append(")", style="dim")

        self.update(text)

    def _render_chop_display(self) -> None:
        """Render the chop-detail status header."""
        text = Text(no_wrap=True, overflow="ellipsis")

        # Chop name + parent lumberjack — color each name in its sidebar hue
        # so the header echoes the row taxonomy of the sidebar tree.
        text.append("[", style="dim")
        text.append(self._chop_lumberjack_name, style=_LJ_NAME_STYLE)
        text.append(" / ", style="dim")
        text.append(self._chop_name, style=_CHOP_NAME_STYLE)
        text.append("]", style="dim")

        run = self._chop_run
        if run is not None:
            entry = run.entry
            is_running = entry.status == "running"
            is_active = entry.status in {"running", "launched"}
            text.append("  │  ", style="dim")
            status_text, status_style = _chop_status_label(entry.status)
            text.append(status_text, style=status_style)

            # Started-at (relative)
            text.append("  │  ", style="dim")
            text.append("When: ", style="bold #87D7FF")
            text.append(_format_time_with_relative(entry.started_at), style="#87D7FF")

            # Duration — label changes for active runs to convey "still running".
            text.append("  │  ", style="dim")
            if is_active:
                text.append("Elapsed: ", style="bold #87D7FF")
                text.append(_format_runtime(entry.started_at), style="#00D7AF")
            else:
                text.append("Took: ", style="bold #87D7FF")
                text.append(_format_duration_ms(entry.duration_ms), style="#00D7AF")

            # Exit code when present (non-agent, non-running runs)
            if entry.exit_code is not None and not is_active:
                text.append("  │  ", style="dim")
                text.append("Exit: ", style="bold #87D7FF")
                code_style = "bold red" if entry.exit_code != 0 else "#00D7AF"
                text.append(str(entry.exit_code), style=code_style)

            # PID for active script runs.
            if is_running and entry.pid is not None:
                text.append("  │  ", style="dim")
                text.append("PID: ", style="bold #87D7FF")
                text.append(str(entry.pid), style="#FF87D7")

            # Source marker (manual vs scheduled) — only surface when it
            # is non-default so the header stays compact for scheduled runs.
            if entry.source and entry.source != "scheduled":
                text.append("  │  ", style="dim")
                text.append("Source: ", style="bold #87D7FF")
                text.append(entry.source, style="#FFD700")

            # Run N/M
            text.append("  │  ", style="dim")
            text.append("Run ", style="bold #87D7FF")
            text.append(
                f"{self._chop_run_idx + 1}/{self._chop_run_total}",
                style="bold #00D7AF",
            )
        else:
            text.append("  │  ", style="dim")
            text.append("no runs recorded yet", style="dim italic")

        # Countdown
        if self._countdown > 0:
            text.append("  │  ", style="dim")
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")

        self.update(text)

    def _render_lumberjack_display(self) -> None:
        """Render the lumberjack-specific status display."""
        text = Text(no_wrap=True, overflow="ellipsis")
        status = self._lumberjack_status

        # Lumberjack name with index
        text.append(f"[{self._lumberjack_name}]", style=_LJ_NAME_STYLE)
        text.append(
            f" ({self._lumberjack_idx + 1}/{self._lumberjack_total})",
            style="dim",
        )

        if status:
            # Status
            text.append("  │  ", style="dim")
            if status.status == "running":
                text.append("RUNNING", style="bold green")
            elif status.status == "error":
                text.append("ERROR", style="bold red")
            else:
                text.append("STOPPED", style="bold #FFD700")

            # PID
            text.append("  │  ", style="dim")
            text.append("PID: ", style="bold #87D7FF")
            text.append(f"{status.pid}", style="#FF87D7 bold")

            # Interval
            text.append("  │  ", style="dim")
            text.append("Interval: ", style="bold #87D7FF")
            text.append(f"{status.interval}s", style="#00D7AF")

            # Cycles
            text.append("  │  ", style="dim")
            text.append("Cycles: ", style="bold #87D7FF")
            text.append(f"{status.cycles_run}", style="#00D7AF bold")

            # Errors
            if status.errors_encountered > 0:
                text.append("  │  ", style="dim")
                text.append("Errors: ", style="bold #87D7FF")
                text.append(f"{status.errors_encountered}", style="bold red")

            # Chops count
            text.append("  │  ", style="dim")
            text.append("Chops: ", style="bold #87D7FF")
            text.append(f"{len(status.chops)}", style="#00D7AF")

        # Countdown
        if self._countdown > 0:
            text.append("  │  ", style="dim")
            text.append("(auto-refresh in ", style="dim")
            text.append(f"{self._countdown}s", style="bold #FFD700")
            text.append(")", style="dim")

        self.update(text)
