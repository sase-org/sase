"""Rendering and formatting helpers for the axe dashboard widget."""

from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.axe.state import LumberjackStatus
from sase.core.time import get_timezone

if TYPE_CHECKING:
    from ..actions.axe_display._data import ChopSnapshot

# Sidebar-coherent palette echoed in the dashboard. Lumberjack names use the
# top-level gold accent, chop names use the dim-copper child hue, and bgcmd
# detail kept the teal/cyan tone from the sidebar. Generic field labels stay
# on the existing blue so the right panel does not turn into one dominant hue.
LJ_NAME_STYLE = "bold #FFD700"
CHOP_NAME_STYLE = "#D7AF87"


def chop_status_label(status: str) -> tuple[str, str]:
    """Return (label, rich style) for a chop run status."""
    if status == "success":
        return ("✓ success", "bold green")
    if status == "failure":
        return ("✗ failure", "bold red")
    if status == "timeout":
        return ("⏱ timeout", "bold yellow")
    if status == "missing_script":
        return ("? missing", "bold yellow")
    if status == "running":
        return ("● running", "bold green")
    return (status, "dim")


def format_duration_ms(duration_ms: int) -> str:
    """Format a millisecond duration for compact display."""
    if duration_ms < 1000:
        return f"{duration_ms}ms"
    seconds = duration_ms / 1000.0
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = int(seconds - minutes * 60)
    return f"{minutes}m {rem}s"


def format_uptime(seconds: int) -> str:
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


def format_runtime(started_at: str) -> str:
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
        return format_uptime(int(elapsed.total_seconds()))
    except (ValueError, TypeError):
        return "unknown"


def format_elapsed(started_at: str, finished_at: str | None) -> str:
    """Format elapsed time between start and finish.

    Args:
        started_at: ISO format start timestamp string.
        finished_at: ISO format finish timestamp string, or None if still running.

    Returns:
        Formatted string like "2h 34m 12s".
    """
    if finished_at is None:
        return format_runtime(started_at)  # Still counting
    try:
        start_time = datetime.fromisoformat(started_at)
        end_time = datetime.fromisoformat(finished_at)
        elapsed = end_time - start_time
        return format_uptime(int(elapsed.total_seconds()))
    except (ValueError, TypeError):
        return "unknown"


def format_relative_time(iso_timestamp: str) -> str:
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


def format_time_with_relative(iso_timestamp: str) -> str:
    """Format an ISO timestamp as local clock time plus current relative age."""
    relative = format_relative_time(iso_timestamp)
    if relative == "unknown":
        return "unknown"

    try:
        ts = datetime.fromisoformat(iso_timestamp)
    except (ValueError, TypeError):
        return "unknown"

    if ts.tzinfo is None:
        return "unknown"

    return f"{ts.astimezone(get_timezone()).strftime('%H:%M:%S')} ({relative})"


def section_width(section: Static) -> int | None:
    """Return the rendered width of ``section`` if known.

    The dashboard threads the output section's actual width into the chop
    table / activity summary renderers so they can degrade to a compact
    layout on narrow terminals. Returns ``None`` when the widget has not
    been laid out yet (``size`` is ``(0, 0)`` pre-mount) so the renderers
    fall back to their wide-default layout.
    """
    try:
        width = int(section.size.width)
    except (AttributeError, TypeError, ValueError):
        return None
    return width if width > 0 else None


def tail_lines(text: str, max_lines: int) -> str:
    """Return the last ``max_lines`` lines of ``text`` (with their newlines)."""
    if not text or max_lines <= 0:
        return ""
    lines = text.splitlines(keepends=True)
    if len(lines) <= max_lines:
        return text
    return "".join(lines[-max_lines:])


def render_wide_chop_table(text: Text, chops: list["ChopSnapshot"]) -> None:
    """Append the standard four-column chop table to ``text``."""
    text.append("  " + "─" * 68 + "\n", style="dim")
    text.append("  ")
    text.append(f"{'NAME':<20}", style="bold #87D7FF")
    text.append(f"{'LAST RUN':<14}", style="bold #87D7FF")
    text.append(f"{'WHEN':<14}", style="bold #87D7FF")
    text.append(f"{'DURATION':>10}", style="bold #87D7FF")
    text.append("\n")
    text.append("  " + "─" * 68 + "\n", style="dim")

    if not chops:
        text.append("  No chops configured for this lumberjack.\n", style="dim italic")
        return

    for chop in chops:
        text.append("  ")
        name = chop.chop_name
        if len(name) > 18:
            name = name[:15] + "..."
        text.append(f"{name:<20}", style=CHOP_NAME_STYLE)
        if chop.runs:
            latest = chop.runs[0].entry
            status_label, status_style = chop_status_label(latest.status)
            text.append(f"{status_label:<14}", style=status_style)
            text.append(
                f"{format_relative_time(latest.started_at):<14}",
                style="#87D7FF",
            )
            if latest.status == "running":
                # Show elapsed runtime so the row reflects an
                # active subprocess instead of a stale 0ms.
                text.append(
                    f"{format_runtime(latest.started_at):>10}",
                    style="#00D7AF",
                )
            else:
                text.append(
                    f"{format_duration_ms(latest.duration_ms):>10}",
                    style="#00D7AF",
                )
        else:
            text.append(f"{'—':<14}", style="dim")
            text.append(f"{'never':<14}", style="dim")
            text.append(f"{'—':>10}", style="dim")
        text.append("\n")


def render_compact_chop_list(text: Text, chops: list["ChopSnapshot"]) -> None:
    """Append the narrow stacked chop list to ``text``.

    Each chop renders as a short header line plus a metadata line so a
    narrow right panel never truncates names or status mid-cell.
    """
    if not chops:
        text.append("  No chops configured for this lumberjack.\n", style="dim italic")
        return

    for chop in chops:
        text.append("  ")
        text.append(chop.chop_name, style=CHOP_NAME_STYLE)
        text.append("\n")
        text.append("    ")
        if chop.runs:
            latest = chop.runs[0].entry
            status_label, status_style = chop_status_label(latest.status)
            text.append(status_label, style=status_style)
            text.append(" · ", style="dim")
            text.append(
                format_relative_time(latest.started_at),
                style="#87D7FF",
            )
            text.append(" · ", style="dim")
            if latest.status == "running":
                text.append(format_runtime(latest.started_at), style="#00D7AF")
            else:
                text.append(format_duration_ms(latest.duration_ms), style="#00D7AF")
        else:
            text.append("never run", style="dim")
        text.append("\n")


def render_compact_summary_row(
    text: Text,
    name: str,
    status: LumberjackStatus | None,
    chops_executed: int,
) -> None:
    """Render one lumberjack summary entry as a compact stacked row."""
    text.append("  ")
    text.append(name, style=LJ_NAME_STYLE)
    text.append("\n    ")
    if status:
        if status.status == "running":
            text.append("● running", style="bold green")
        elif status.status == "error":
            text.append("● error", style="bold red")
        else:
            text.append("○ stopped", style="#FFD700")
    else:
        text.append("○ unknown", style="dim")
    cycles = status.cycles_run if status else 0
    errors = status.errors_encountered if status else 0
    text.append(" · ", style="dim")
    text.append(f"{cycles}c", style="#00D7AF")
    text.append(" · ", style="dim")
    text.append(f"{chops_executed} chops", style="#00D7AF")
    if errors:
        text.append(" · ", style="dim")
        text.append(f"{errors}e", style="bold red")
    if status and status.last_cycle:
        text.append(" · ", style="dim")
        text.append(format_relative_time(status.last_cycle), style="#87D7FF")
    text.append("\n")
