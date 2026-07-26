"""Axe dashboard widget for the ace TUI."""

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.axe.state import AxeStatus, LumberjackStatus

from ..util.axe_log_renderer import SourceType, render_axe_output
from ..util.trace import tui_trace
from ._axe_dashboard_output import (
    AxeOutputSection,
    LumberjackSummary,
)
from ._axe_dashboard_render import (
    chop_status_label as _chop_status_label,
    format_duration_ms as _format_duration_ms,
    format_runtime as _format_runtime,
    format_uptime as _format_uptime,
    section_width as _section_width,
)
from ._axe_dashboard_status import AxeStatusSection
from .axe_description_banner import AxeDescriptionBanner

# Underscored aliases preserve the original module-level names used by tests
# before the dashboard widget was split into per-section modules.
_AxeStatusSection = AxeStatusSection
_AxeOutputSection = AxeOutputSection

if TYPE_CHECKING:
    from ..actions.axe_display._data import (
        AxeStatusDegradation,
        ChopSnapshot,
        LumberjackSnapshot,
    )
    from ..bgcmd import BackgroundCommandInfo

__all__ = [
    "AxeDashboard",
    "LumberjackSummary",
    "_AxeOutputSection",
    "_AxeStatusSection",
    "_chop_status_label",
    "_format_duration_ms",
    "_format_runtime",
    "_format_uptime",
]


class AxeDashboard(Static):
    """Main dashboard widget combining status bar and output log."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the dashboard."""
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        """Compose the dashboard sections."""
        yield _AxeStatusSection(id="axe-status-section")
        yield AxeDescriptionBanner(id="axe-description-banner")
        with VerticalScroll(id="axe-output-scroll"):
            yield _AxeOutputSection(id="axe-output-section")

    def _description_banner(self) -> AxeDescriptionBanner | None:
        """Return the mounted banner, tolerating lightweight unit-test doubles."""
        banner = self.query_one("#axe-description-banner", AxeDescriptionBanner)
        return banner if isinstance(banner, AxeDescriptionBanner) else None

    def _hide_description_banner(self) -> None:
        banner = self._description_banner()
        if banner is not None:
            banner.hide()

    def _description_max_lines(self) -> int:
        """Return the panel line budget while preserving most output space."""
        height = self.size.height
        if height <= 0:
            return 10
        return max(3, min(16, int(height * 0.45)))

    def _description_expanded(self) -> bool:
        """Read the app's session-only panel state without touching config."""
        try:
            return bool(getattr(self.app, "axe_description_expanded", True))
        except Exception:
            return True

    def refresh_description_banner(self, expanded: bool) -> None:
        """Repaint only the cached description panel for the ``d`` action."""
        banner = self._description_banner()
        if banner is not None:
            banner.set_expanded(expanded)

    def update_display(
        self,
        is_running: bool,
        status: AxeStatus | None,
        output: str,
        full_cycles: int = 0,
        countdown: int = 0,
        lumberjack_summaries: list[LumberjackSummary] | None = None,
        degraded_status: "AxeStatusDegradation | None" = None,
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
            degraded_status: Recoverable collection problem to surface in the pane.
        """
        with tui_trace(
            "widget.axe_dashboard.update_display",
            output_bytes=len(output) if output else 0,
            lumberjacks=len(lumberjack_summaries or []),
        ):
            status_section = self.query_one("#axe-status-section", _AxeStatusSection)
            output_section = self.query_one("#axe-output-section", _AxeOutputSection)

            self._hide_description_banner()
            status_section.update_display(
                status,
                is_running,
                full_cycles,
                countdown,
                degraded_status,
            )

            if lumberjack_summaries:
                output_section.update_lumberjack_summary(
                    lumberjack_summaries, width=_section_width(output_section)
                )
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

    def update_empty_axe_display(
        self,
        *,
        is_running: bool,
        status: AxeStatus | None,
        full_cycles: int,
        countdown: int,
        add_key: str,
        degraded_status: "AxeStatusDegradation | None" = None,
    ) -> None:
        """Show daemon status plus a configured-key zero-lumberjack prompt."""
        status_section = self.query_one("#axe-status-section", _AxeStatusSection)
        output_section = self.query_one("#axe-output-section", _AxeOutputSection)
        self._hide_description_banner()
        status_section.update_display(
            status,
            is_running,
            full_cycles,
            countdown,
            degraded_status,
        )
        output_section.update_empty_axe(add_key)

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

        self._hide_description_banner()
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

        self._hide_description_banner()
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

            description_banner = self._description_banner()
            if description_banner is not None:
                description_banner.set_expanded(self._description_expanded())
                description_banner.set_max_lines(self._description_max_lines())
                description_banner.show_lumberjack(
                    snapshot.name,
                    snapshot.description_summary or snapshot.description,
                    snapshot.description_body,
                )
            status_section.update_lumberjack_display(
                snapshot.status, snapshot.name, idx, total, countdown
            )
            output_section.update_lumberjack_overview(
                snapshot, width=_section_width(output_section)
            )

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

            description_banner = self._description_banner()
            if description_banner is not None:
                description_banner.set_expanded(self._description_expanded())
                description_banner.set_max_lines(self._description_max_lines())
                description_banner.show_chop(
                    snapshot.chop_name,
                    snapshot.description_summary or snapshot.description,
                    snapshot.description_body,
                    generated=snapshot.generated,
                    target_key=snapshot.target_key,
                )
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
                output_section.update(
                    Text("No runs recorded for this chop yet.", style="dim italic")
                )
                return

            source_id = (
                f"chop:{snapshot.lumberjack_name}:{snapshot.chop_name}"
                f":{run.entry.run_id}"
            )
            # Chop script output is arbitrary, so retain ANSI rendering.
            chop_source_type: SourceType = "ansi"
            if run.output_tail:
                output_section.update_display(
                    run.output_tail,
                    source_id=source_id,
                    source_type=chop_source_type,
                )
            else:
                empty = Text()
                if run.entry.status in {"running", "launched"}:
                    empty.append("Waiting for output…", style="dim italic")
                elif run.entry.error:
                    empty.append(run.entry.error, style="bold red")
                    if run.entry.traceback:
                        empty.append("\n\n")
                        empty.append(run.entry.traceback, style="dim red")
                elif run.entry.reason:
                    empty.append(run.entry.reason, style="yellow")
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
