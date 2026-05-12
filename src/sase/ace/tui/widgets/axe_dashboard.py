"""Axe dashboard widget for the ace TUI."""

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sase.axe.state import AxeStatus, LumberjackStatus
from sase.core.time import get_timezone
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

if TYPE_CHECKING:
    from ..actions.axe_display._data import (
        ChopRunSnapshot,
        ChopSnapshot,
        LumberjackSnapshot,
    )
    from ..bgcmd import BackgroundCommandInfo

from ..util.axe_log_renderer import SourceType, render_axe_output
from ..util.trace import tui_trace

# Type alias for lumberjack summary tuple: (name, status, chops_executed)
LumberjackSummary = tuple[str, LumberjackStatus | None, int]


def _chop_status_label(status: str) -> tuple[str, str]:
    """Return (label, rich style) for a chop run status."""
    if status == "success":
        return ("✓ success", "bold green")
    if status == "failure":
        return ("✗ failure", "bold red")
    if status == "timeout":
        return ("⏱ timeout", "bold yellow")
    if status == "missing_script":
        return ("? missing", "bold yellow")
    if status == "agent_launched":
        return ("→ agent", "bold #00D7AF")
    if status == "running":
        return ("● running", "bold green")
    return (status, "dim")


def _format_duration_ms(duration_ms: int) -> str:
    """Format a millisecond duration for compact display."""
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = int(seconds - minutes * 60)
    return f"{minutes}m {rem}s"


class _AxeStatusSection(Static):
    """Compact status bar showing runtime, cycles, and runners."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the status section."""
        super().__init__(**kwargs)
        # State for axe daemon mode
        self._axe_mode = True
        self._status: AxeStatus | None = None
        self._is_running = False
        self._full_cycles = 0
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
    ) -> None:
        """Update the compact status section for axe daemon.

        Args:
            status: Current axe status, or None if not available.
            is_running: Whether axe daemon is currently running.
            full_cycles: Number of full cycles run.
            countdown: Seconds until next auto-refresh.
        """
        self._axe_mode = True
        self._lumberjack_mode = False
        self._status = status
        self._is_running = is_running
        self._full_cycles = full_cycles
        self._countdown = countdown
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
        text = Text()

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
        text = Text()
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
            text.append(info.project, style="#00D7AF")

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
        text = Text()

        # Chop name + parent lumberjack
        text.append(
            f"[{self._chop_lumberjack_name} / {self._chop_name}]",
            style="bold #FFD700",
        )

        run = self._chop_run
        if run is not None:
            entry = run.entry
            is_running = entry.status == "running"
            text.append("  │  ", style="dim")
            status_text, status_style = _chop_status_label(entry.status)
            text.append(status_text, style=status_style)

            # Started-at (relative)
            text.append("  │  ", style="dim")
            text.append("When: ", style="bold #87D7FF")
            text.append(_format_relative_time(entry.started_at), style="#87D7FF")

            # Duration — label changes for active runs to convey "still running".
            text.append("  │  ", style="dim")
            if is_running:
                text.append("Elapsed: ", style="bold #87D7FF")
                text.append(_format_runtime(entry.started_at), style="#00D7AF")
            else:
                text.append("Took: ", style="bold #87D7FF")
                text.append(_format_duration_ms(entry.duration_ms), style="#00D7AF")

            # Exit code when present (non-agent, non-running runs)
            if entry.exit_code is not None and not is_running:
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
        text = Text()
        status = self._lumberjack_status

        # Lumberjack name with index
        text.append(f"[{self._lumberjack_name}]", style="bold #FFD700")
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


class _AxeOutputSection(Static):
    """Section showing live axe output log."""

    def update_display(
        self,
        output: str,
        source_id: str = "axe-output",
        source_type: SourceType = "ansi",
    ) -> None:
        """Update the output section with log content.

        Args:
            output: Raw output with ANSI codes.
            source_id: Cache slot name (defaults to the daemon log; lumberjack
                output passes a per-name slot so distinct logs don't collide).
            source_type: Selects between semantic highlighters for known
                AXE-controlled formats and the ANSI fallback for arbitrary
                external output. Cache slots are keyed on
                ``(source_id, source_type)`` so the two paths can't collide.
        """
        if not output:
            text = Text("No output yet. Start axe with ", style="dim italic")
            text.append("x", style="bold #FFD700")
            text.append(" to see live output.", style="dim italic")
            self.update(text)
            return

        text = render_axe_output(source_id, output, source_type)
        self.update(text)

    def update_lumberjack_overview(self, snapshot: "LumberjackSnapshot") -> None:
        """Render a single lumberjack's overview: status + per-chop table.

        Args:
            snapshot: Cached lumberjack snapshot.
        """
        text = Text()
        status = snapshot.status
        metrics = snapshot.metrics

        # Status / interval / cycles / errors line
        text.append("  ")
        text.append("Status: ", style="bold #87D7FF")
        if status is None:
            text.append("unknown", style="dim")
        elif status.status == "running":
            text.append("● running", style="bold green")
        elif status.status == "error":
            text.append("● error", style="bold red")
        else:
            text.append("○ stopped", style="#FFD700")

        if status is not None:
            text.append("    ")
            text.append("Interval: ", style="bold #87D7FF")
            text.append(f"{status.interval}s", style="#00D7AF")
            text.append("    ")
            text.append("Cycles: ", style="bold #87D7FF")
            text.append(f"{status.cycles_run}", style="#00D7AF")
            text.append("    ")
            text.append("Errors: ", style="bold #87D7FF")
            err_style = "bold red" if status.errors_encountered else "dim"
            text.append(f"{status.errors_encountered}", style=err_style)

        if metrics is not None:
            text.append("    ")
            text.append("Chops run: ", style="bold #87D7FF")
            text.append(f"{metrics.chops_executed}", style="#00D7AF")

        text.append("\n\n")

        # Chops table
        chops = snapshot.chops
        text.append("  CHOPS\n", style="bold #FFD700")
        text.append("  " + "─" * 68 + "\n", style="dim")
        text.append("  ")
        text.append(f"{'NAME':<20}", style="bold #87D7FF")
        text.append(f"{'LAST RUN':<14}", style="bold #87D7FF")
        text.append(f"{'WHEN':<14}", style="bold #87D7FF")
        text.append(f"{'DURATION':>10}", style="bold #87D7FF")
        text.append("\n")
        text.append("  " + "─" * 68 + "\n", style="dim")

        if not chops:
            text.append(
                "  No chops configured for this lumberjack.\n", style="dim italic"
            )
        else:
            for chop in chops:
                text.append("  ")
                name = chop.chop_name
                if len(name) > 18:
                    name = name[:15] + "..."
                text.append(f"{name:<20}", style="#FFFFFF")
                if chop.runs:
                    latest = chop.runs[0].entry
                    status_label, status_style = _chop_status_label(latest.status)
                    text.append(f"{status_label:<14}", style=status_style)
                    text.append(
                        f"{_format_relative_time(latest.started_at):<14}",
                        style="#87D7FF",
                    )
                    if latest.status == "running":
                        # Show elapsed runtime so the row reflects an
                        # active subprocess instead of a stale 0ms.
                        text.append(
                            f"{_format_runtime(latest.started_at):>10}",
                            style="#00D7AF",
                        )
                    else:
                        text.append(
                            f"{_format_duration_ms(latest.duration_ms):>10}",
                            style="#00D7AF",
                        )
                else:
                    text.append(f"{'—':<14}", style="dim")
                    text.append(f"{'never':<14}", style="dim")
                    text.append(f"{'—':>10}", style="dim")
                text.append("\n")

        self.update(text)

    def update_lumberjack_summary(self, summaries: list[LumberjackSummary]) -> None:
        """Render a summary of all lumberjack activity.

        Args:
            summaries: List of (name, status, chops_executed) tuples.
        """
        if not summaries:
            text = Text("No lumberjacks configured.", style="dim italic")
            self.update(text)
            return

        text = Text()

        # Header
        text.append("  JACK ACTIVITY\n", style="bold #FFD700")
        text.append("  " + "─" * 68 + "\n", style="dim")

        # Column header
        text.append("  ")
        text.append(f"{'NAME':<16}", style="bold #87D7FF")
        text.append(f"{'STATUS':<12}", style="bold #87D7FF")
        text.append(f"{'CYCLES':>8}", style="bold #87D7FF")
        text.append(f"{'CHOPS':>8}", style="bold #87D7FF")
        text.append(f"{'ERRORS':>8}", style="bold #87D7FF")
        text.append("  ")
        text.append(f"{'LAST CYCLE':<18}", style="bold #87D7FF")
        text.append("\n")
        text.append("  " + "─" * 68 + "\n", style="dim")

        for name, status, chops_executed in summaries:
            text.append("  ")

            # Name
            text.append(f"{name:<16}", style="bold #FFFFFF")

            # Status indicator
            if status:
                if status.status == "running":
                    text.append(f"{'● running':<12}", style="bold green")
                elif status.status == "error":
                    text.append(f"{'● error':<12}", style="bold red")
                else:
                    text.append(f"{'○ stopped':<12}", style="#FFD700")
            else:
                text.append(f"{'○ unknown':<12}", style="dim")

            # Cycles
            cycles = status.cycles_run if status else 0
            text.append(f"{cycles:>8}", style="#00D7AF")

            # Chops executed (from metrics)
            text.append(f"{chops_executed:>8}", style="#00D7AF")

            # Errors
            errors = status.errors_encountered if status else 0
            if errors > 0:
                text.append(f"{errors:>8}", style="bold red")
            else:
                text.append(f"{errors:>8}", style="dim")

            # Last cycle (relative time)
            text.append("  ")
            if status and status.last_cycle:
                text.append(_format_relative_time(status.last_cycle), style="#87D7FF")
            else:
                text.append("never", style="dim")

            text.append("\n")

        text.append("  " + "─" * 68 + "\n", style="dim")

        # Summary footer
        total_cycles = sum(s.cycles_run for _, s, _ in summaries if s is not None)
        total_errors = sum(
            s.errors_encountered for _, s, _ in summaries if s is not None
        )
        running_count = sum(
            1 for _, s, _ in summaries if s is not None and s.status == "running"
        )

        text.append("\n  ")
        text.append(f"{running_count}", style="bold green")
        text.append(f"/{len(summaries)} running", style="dim")
        text.append("    ", style="")
        text.append(f"{total_cycles}", style="bold #00D7AF")
        text.append(" total cycles", style="dim")
        if total_errors > 0:
            text.append("    ", style="")
            text.append(f"{total_errors}", style="bold red")
            text.append(" total errors", style="dim")
        text.append("\n")

        # Hint
        text.append("\n  ")
        text.append("Ctrl+N", style="bold #00D7AF")
        text.append("/", style="dim")
        text.append("Ctrl+P", style="bold #00D7AF")
        text.append(" to cycle through lumberjack views", style="dim")

        self.update(text)


class AxeDashboard(Static):
    """Main dashboard widget combining status bar and output log."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the dashboard."""
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        """Compose the dashboard sections."""
        yield _AxeStatusSection(id="axe-status-section")
        with VerticalScroll(id="axe-output-scroll"):
            yield _AxeOutputSection(id="axe-output-section")

    def update_display(
        self,
        is_running: bool,
        status: AxeStatus | None,
        output: str,
        full_cycles: int = 0,
        countdown: int = 0,
        lumberjack_summaries: list[LumberjackSummary] | None = None,
    ) -> None:
        """Update all dashboard sections with current data.

        Args:
            is_running: Whether axe daemon is currently running.
            status: Current axe status, or None if not available.
            output: Raw output log with ANSI codes.
            full_cycles: Number of full cycles run.
            countdown: Seconds until next auto-refresh.
            lumberjack_summaries: Per-lumberjack (name, status, chops_executed)
                tuples for the activity summary, or None to skip.
        """
        with tui_trace(
            "widget.axe_dashboard.update_display",
            output_bytes=len(output) if output else 0,
            lumberjacks=len(lumberjack_summaries or []),
        ):
            status_section = self.query_one("#axe-status-section", _AxeStatusSection)
            output_section = self.query_one("#axe-output-section", _AxeOutputSection)

            status_section.update_display(status, is_running, full_cycles, countdown)

            if lumberjack_summaries:
                output_section.update_lumberjack_summary(lumberjack_summaries)
            else:
                output_section.update_display(output)

    def show_empty(self) -> None:
        """Show empty/stopped state."""
        self.update_display(
            is_running=False,
            status=None,
            output="",
            full_cycles=0,
        )

    def update_bgcmd_display(
        self,
        info: "BackgroundCommandInfo | None",
        output: str,
        is_running: bool,
        countdown: int = 0,
    ) -> None:
        """Update the dashboard to show background command info and output.

        Args:
            info: Background command info.
            output: Raw output log with ANSI codes.
            is_running: Whether the command is still running.
            countdown: Seconds until next auto-refresh.
        """
        status_section = self.query_one("#axe-status-section", _AxeStatusSection)
        output_section = self.query_one("#axe-output-section", _AxeOutputSection)

        status_section.update_bgcmd_display(info, is_running, countdown)

        # Update output section
        if not output:
            text = Text()
            if is_running:
                text.append("Waiting for output...", style="dim italic")
            else:
                text.append("No output.", style="dim italic")
            output_section.update(text)
        else:
            # Bgcmd output is arbitrary user-process text: stay on the ANSI
            # fallback so terminal colors round-trip without us inventing
            # syntax highlighting for external command output.
            info_id = info.pid if info is not None else "unset"
            text = render_axe_output(f"bgcmd:{info_id}", output, "ansi")
            output_section.update(text)

    def update_lumberjack_display(
        self,
        name: str,
        idx: int,
        total: int,
        status: LumberjackStatus | None,
        output: str,
        countdown: int = 0,
    ) -> None:
        """Update the dashboard to show a specific lumberjack's output.

        Args:
            name: Lumberjack name.
            idx: Current index (0-based).
            total: Total number of lumberjacks.
            status: Lumberjack status, or None if not available.
            output: Raw output log with ANSI codes.
            countdown: Seconds until next auto-refresh.
        """
        status_section = self.query_one("#axe-status-section", _AxeStatusSection)
        output_section = self.query_one("#axe-output-section", _AxeOutputSection)

        status_section.update_lumberjack_display(status, name, idx, total, countdown)
        output_section.update_display(
            output,
            source_id=f"lumberjack:{name}",
            source_type="lumberjack",
        )

    def update_lumberjack_overview(
        self,
        snapshot: "LumberjackSnapshot",
        idx: int,
        total: int,
        countdown: int = 0,
    ) -> None:
        """Update the dashboard with the lumberjack overview view.

        Shows lumberjack runtime status in the header and a per-chop
        table (last-run status + time) in the body so the user can see
        what is configured under this lumberjack without expanding it.

        Args:
            snapshot: Cached lumberjack snapshot (status, metrics, chops).
            idx: Current 0-based lumberjack index.
            total: Total number of configured lumberjacks.
            countdown: Seconds until next auto-refresh.
        """
        with tui_trace(
            "widget.axe_dashboard.update_lumberjack_overview",
            lumberjack=snapshot.name,
            chops=len(snapshot.chops),
        ):
            status_section = self.query_one("#axe-status-section", _AxeStatusSection)
            output_section = self.query_one("#axe-output-section", _AxeOutputSection)

            status_section.update_lumberjack_display(
                snapshot.status, snapshot.name, idx, total, countdown
            )
            output_section.update_lumberjack_overview(snapshot)

    def update_chop_run_display(
        self,
        snapshot: "ChopSnapshot",
        run_idx: int,
        countdown: int = 0,
    ) -> None:
        """Update the dashboard with a chop's selected run output.

        Args:
            snapshot: Cached chop snapshot (newest-first run history).
            run_idx: 0-based index of the run to display (0 = newest).
                Clamped to the available history range.
            countdown: Seconds until next auto-refresh.
        """
        runs = snapshot.runs
        run_total = len(runs)
        if run_total == 0:
            run = None
            display_idx = 0
        else:
            display_idx = max(0, min(run_idx, run_total - 1))
            run = runs[display_idx]

        with tui_trace(
            "widget.axe_dashboard.update_chop_run_display",
            lumberjack=snapshot.lumberjack_name,
            chop=snapshot.chop_name,
            run_total=run_total,
            run_idx=display_idx,
        ):
            status_section = self.query_one("#axe-status-section", _AxeStatusSection)
            output_section = self.query_one("#axe-output-section", _AxeOutputSection)

            status_section.update_chop_display(
                snapshot.lumberjack_name,
                snapshot.chop_name,
                run,
                display_idx,
                run_total,
                countdown,
            )

            if run is None:
                # Empty state: configured chop with no recorded runs.
                empty = Text()
                empty.append(
                    "No runs recorded for this chop yet.\n", style="dim italic"
                )
                if snapshot.description:
                    empty.append("\n  ", style="")
                    empty.append(snapshot.description, style="dim")
                output_section.update(empty)
                return

            source_id = (
                f"chop:{snapshot.lumberjack_name}:{snapshot.chop_name}"
                f":{run.entry.run_id}"
            )
            # Agent chop runs emit a single controlled launch line; route
            # those through the semantic highlighter. External script output
            # stays on the ANSI fallback — its content is arbitrary.
            if run.entry.status == "agent_launched":
                chop_source_type: SourceType = "chop_controlled"
            else:
                chop_source_type = "ansi"
            if run.output_tail:
                output_section.update_display(
                    run.output_tail,
                    source_id=source_id,
                    source_type=chop_source_type,
                )
            else:
                empty = Text()
                if run.entry.status == "agent_launched":
                    empty.append(
                        "Agent was launched for this chop run; output is "
                        "captured in the agent's own logs.",
                        style="dim italic",
                    )
                elif run.entry.status == "running":
                    empty.append("Waiting for output…", style="dim italic")
                elif run.entry.error:
                    empty.append(run.entry.error, style="bold red")
                    if run.entry.traceback:
                        empty.append("\n\n")
                        empty.append(run.entry.traceback, style="dim red")
                else:
                    empty.append("Run captured no output.", style="dim italic")
                output_section.update(empty)

    def update_countdown(self, countdown: int) -> None:
        """Update just the countdown display.

        This is called every second by the countdown tick handler.

        Args:
            countdown: Seconds until next auto-refresh.
        """
        status_section = self.query_one("#axe-status-section", _AxeStatusSection)
        status_section.update_countdown(countdown)


def _format_uptime(seconds: int) -> str:
    """Format uptime seconds into human-readable string.

    Args:
        seconds: Total uptime in seconds.

    Returns:
        Formatted string like "2h 34m 12s".
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)


def _format_runtime(started_at: str) -> str:
    """Format runtime from ISO timestamp to human-readable string.

    Args:
        started_at: ISO format timestamp string.

    Returns:
        Formatted string like "2h 34m 12s".
    """
    try:
        start_time = datetime.fromisoformat(started_at)
        now = datetime.now(get_timezone())
        elapsed = now - start_time
        return _format_uptime(int(elapsed.total_seconds()))
    except (ValueError, TypeError):
        return "unknown"


def _format_elapsed(started_at: str, finished_at: str | None) -> str:
    """Format elapsed time between start and finish.

    Args:
        started_at: ISO format start timestamp string.
        finished_at: ISO format finish timestamp string, or None if still running.

    Returns:
        Formatted string like "2h 34m 12s".
    """
    if finished_at is None:
        return _format_runtime(started_at)  # Still counting
    try:
        start_time = datetime.fromisoformat(started_at)
        end_time = datetime.fromisoformat(finished_at)
        elapsed = end_time - start_time
        return _format_uptime(int(elapsed.total_seconds()))
    except (ValueError, TypeError):
        return "unknown"


def _format_relative_time(iso_timestamp: str) -> str:
    """Format an ISO timestamp as a relative time string like '30s ago'.

    Args:
        iso_timestamp: ISO format timestamp string.

    Returns:
        Relative time string, e.g. "30s ago", "5m ago", "2h ago".
    """
    try:
        ts = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(get_timezone())
        elapsed = int((now - ts).total_seconds())
        if elapsed < 0:
            return "just now"
        if elapsed < 60:
            return f"{elapsed}s ago"
        if elapsed < 3600:
            return f"{elapsed // 60}m ago"
        return f"{elapsed // 3600}h ago"
    except (ValueError, TypeError):
        return "unknown"
