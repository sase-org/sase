"""Output-log section for the axe dashboard widget."""

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.axe.state import LumberjackStatus

from ..util.axe_log_renderer import SourceType, render_axe_output
from ._axe_dashboard_render import (
    LJ_NAME_STYLE as _LJ_NAME_STYLE,
    format_relative_time as _format_relative_time,
    render_compact_chop_list as _render_compact_chop_list,
    render_compact_summary_row as _render_compact_summary_row,
    render_wide_chop_table as _render_wide_chop_table,
    tail_lines as _tail_lines,
)

if TYPE_CHECKING:
    from ..actions.axe_display._data import LumberjackSnapshot

# Type alias for lumberjack summary tuple: (name, status, chops_executed)
LumberjackSummary = tuple[str, LumberjackStatus | None, int]

# Width thresholds where the per-chop and per-lumberjack tables degrade to a
# compact stacked layout instead of overflowing the right panel. Picked from
# the natural column widths used in the wide renderers below.
_NARROW_OVERVIEW_WIDTH = 60
_NARROW_SUMMARY_WIDTH = 70

# Lumberjack log-tail footer in the overview view — capped so the chop table
# is never crowded out. Counted in lines from the tail.
_OVERVIEW_LOG_TAIL_LINES = 6


class AxeOutputSection(Static):
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

    def update_empty_axe(self, add_key: str) -> None:
        """Render the zero-lumberjack call to action from cached key metadata."""
        text = Text("No lumberjacks configured.\n\n", style="dim italic")
        text.append("  ")
        text.append(add_key, style="bold reverse #FFD700")
        text.append("  Add a lumberjack or chop to AXE.", style="#D7AF87")
        text.append("\n\nBackground commands remain available with !!.", style="dim")
        self.update(text)

    def update_lumberjack_overview(
        self,
        snapshot: "LumberjackSnapshot",
        width: int | None = None,
    ) -> None:
        """Render a single lumberjack's overview: status + per-chop table.

        Args:
            snapshot: Cached lumberjack snapshot.
            width: Available cell width for the right panel. When tight
                (``< _NARROW_OVERVIEW_WIDTH``) the chop table degrades to a
                compact stacked layout so the panel never overflows. ``None``
                or non-positive values render the full-width layout.
        """
        text = Text()
        status = snapshot.status
        metrics = snapshot.metrics
        is_narrow = width is not None and 0 < width < _NARROW_OVERVIEW_WIDTH

        # Status / interval / cycles / errors line. The full-width layout
        # joins fields with four-space gaps; the narrow layout stacks them
        # one field per line so a narrow panel never truncates mid-value.
        sep = "\n  " if is_narrow else "    "
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
            text.append(sep)
            text.append("Interval: ", style="bold #87D7FF")
            text.append(f"{status.interval}s", style="#00D7AF")
            text.append(sep)
            text.append("Cycles: ", style="bold #87D7FF")
            text.append(f"{status.cycles_run}", style="#00D7AF")
            text.append(sep)
            text.append("Errors: ", style="bold #87D7FF")
            err_style = "bold red" if status.errors_encountered else "dim"
            text.append(f"{status.errors_encountered}", style=err_style)

        if metrics is not None:
            text.append(sep)
            text.append("Chops run: ", style="bold #87D7FF")
            text.append(f"{metrics.chops_executed}", style="#00D7AF")

        text.append("\n\n")

        # Chops table — choose the wide table or the compact stack based on
        # the available width.
        chops = snapshot.chops
        text.append("  CHOPS\n", style=_LJ_NAME_STYLE)
        if is_narrow:
            _render_compact_chop_list(text, chops)
        else:
            _render_wide_chop_table(text, chops)

        # Optional log-tail footer. Only added when the cache has a tail so
        # quiet lumberjacks don't get a stray empty section. The semantic
        # highlighter is reused from the dashboard's log path so colors are
        # consistent across views; a distinct cache slot prevents collisions
        # with ``update_lumberjack_display``'s full-log render.
        if snapshot.log_tail:
            tail = _tail_lines(snapshot.log_tail, _OVERVIEW_LOG_TAIL_LINES)
            if tail:
                text.append("\n  RECENT LOG\n", style=_LJ_NAME_STYLE)
                text.append("  " + "─" * 68 + "\n", style="dim")
                highlighted = render_axe_output(
                    f"lumberjack:{snapshot.name}:overview-tail",
                    tail,
                    "lumberjack",
                )
                lines = highlighted.split(allow_blank=False)
                for line in lines:
                    text.append("  ")
                    text.append_text(line)
                    text.append("\n")

        self.update(text)

    def update_lumberjack_summary(
        self,
        summaries: list[LumberjackSummary],
        width: int | None = None,
    ) -> None:
        """Render a summary of all lumberjack activity.

        Args:
            summaries: List of (name, status, chops_executed) tuples.
        """
        if not summaries:
            text = Text("No lumberjacks configured.", style="dim italic")
            self.update(text)
            return

        text = Text()
        is_narrow = width is not None and 0 < width < _NARROW_SUMMARY_WIDTH

        # Header
        text.append("  JACK ACTIVITY\n", style=_LJ_NAME_STYLE)
        text.append("  " + "─" * 68 + "\n", style="dim")

        if is_narrow:
            for name, status, chops_executed in summaries:
                _render_compact_summary_row(text, name, status, chops_executed)
        else:
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

                # Lumberjack name in the sidebar's gold accent.
                text.append(f"{name:<16}", style=_LJ_NAME_STYLE)

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
                    text.append(
                        _format_relative_time(status.last_cycle),
                        style="#87D7FF",
                    )
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
