"""Chop-run output rendering for the axe dashboard widget."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets import Static

from sase.axe.chop_report_render import render_section_rule

from ..util.axe_log_renderer import SourceType, render_axe_output
from ._axe_chop_result_card import render_cached_chop_card_and_report

if TYPE_CHECKING:
    from sase.axe.state import ChopRunEntry


def render_origin_detail_line(source: str, declared_by: str) -> Text | None:
    """Return the ``Source: <source> (<declared_by>)`` detail line, if known.

    Shared by the routine overview and job detail bodies so both use the
    service-proc wording. This is configuration origin (first declaring
    layer), never execution source (``scheduled``/``manual``/``oneshot``).
    Returns None when the snapshot carries no origin (synthetic snapshots
    built without a config), in which case callers render no line rather
    than an arbitrary panel claim.
    """
    if not source:
        return None
    line = Text()
    line.append("  ")
    line.append("Source: ", style="bold #87D7FF")
    line.append(f"{source} ({declared_by})", style="dim")
    return line


class AxeChopOutputMixin(Static):
    """Mixin providing chop-run and generic log rendering."""

    _cached_lumberjack_overview: Any
    _cached_lumberjack_overview_layout: Any

    def update_chop_run(
        self,
        lumberjack_name: str,
        chop_name: str,
        entry: ChopRunEntry,
        output: str,
        *,
        width: int | None = None,
        source: str = "",
        declared_by: str = "",
    ) -> None:
        """Render a cached RESULT card, optional REPORT, and ANSI OUTPUT.

        The ``source``/``declared_by`` pair is the job's configuration
        origin and is rendered ahead of the run-scoped card so it never
        mixes with the run's execution source. It stays outside the
        card cache, which is keyed on run identity alone.
        """
        self._cached_lumberjack_overview = None
        self._cached_lumberjack_overview_layout = None
        text = Text()
        origin_line = render_origin_detail_line(source, declared_by)
        if origin_line is not None:
            text.append_text(origin_line)
            text.append("\n\n")
        text.append_text(
            render_cached_chop_card_and_report(
                lumberjack_name,
                chop_name,
                entry,
                width=width,
            )
        )
        line_count = len(output.splitlines()) if output else 0
        text.append("\n\n")
        line_label = "line" if line_count == 1 else "lines"
        text.append_text(
            render_section_rule(f"OUTPUT · {line_count} {line_label}", width=width)
        )
        text.append("\n")

        if output:
            source_id = f"chop:{lumberjack_name}:{chop_name}:{entry.run_id}"
            text.append_text(render_axe_output(source_id, output, "ansi"))
        elif entry.status in {"running", "launched"}:
            text.append("  Waiting for output…", style="dim italic")
        elif entry.error:
            text.append(f"  {entry.error}", style="bold red")
            if entry.traceback:
                text.append("\n\n")
                text.append(entry.traceback, style="dim red")
        elif entry.reason:
            text.append(f"  {entry.reason}", style="yellow")
        else:
            text.append("  Run captured no output.", style="dim italic")
        self.update(text)

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
        self._cached_lumberjack_overview = None
        self._cached_lumberjack_overview_layout = None
        if not output:
            text = Text("No output yet. Start axe with ", style="dim italic")
            text.append("x", style="bold #FFD700")
            text.append(" to see live output.", style="dim italic")
            self.update(text)
            return

        text = render_axe_output(source_id, output, source_type)
        self.update(text)
