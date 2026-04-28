"""Pure helpers for the ChangeSpec list widget.

Houses mentor-stat aggregation, status-indicator computation, row signature
hashing, width calculation, and the per-row Option formatter.  Kept free
of widget state so :mod:`changespec_list` can stay focused on the
``OptionList`` subclass.
"""

import logging
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from ...changespec import (
    ChangeSpec,
    get_base_status,
    has_any_error_suffix,
    has_any_running_agent,
    has_any_running_process,
)
from ...mentor_output import (
    load_acceptance_state,
    load_mentor_outputs_for_commit,
    load_read_state,
)

log = logging.getLogger(__name__)

_PREFIX_CHAR_COLORS: dict[str, str] = {
    "!": "#FF5F5F",  # Red for error
    "@": "#FFAF00",  # Orange for running agent
    "$": "#D7AF00",  # Darker yellow for running process
}


# ── Mentor comment stats ────────────────────────────────────────────────


@dataclass
class _MentorCommentStats:
    """Aggregate mentor comment stats for display in the CL list."""

    total: int
    unread: int
    accepted: int


def compute_mentor_stats(changespec: ChangeSpec) -> _MentorCommentStats | None:
    """Compute mentor comment stats for the latest commit entry.

    Returns None if there are no finished mentors with comments.
    """
    if not changespec.mentors:
        return None
    try:
        latest_entry = max(changespec.mentors, key=lambda e: e.entry_id)
        if not latest_entry.status_lines:
            return None

        finished_statuses = {"PASSED", "COMMENTED", "FAILED"}
        finished_lines = [
            sl for sl in latest_entry.status_lines if sl.status in finished_statuses
        ]
        if not finished_lines:
            return None

        timestamps = {sl.timestamp for sl in finished_lines}
        cl_name = changespec.name
        outputs = load_mentor_outputs_for_commit(cl_name, timestamps)

        # Map timestamps to outputs
        ts_map: dict[str, Any] = {}
        for path, mo in outputs:
            for ts in timestamps:
                if path.stem.endswith(f"-{ts}"):
                    ts_map[ts] = mo
                    break

        entry_id = latest_entry.entry_id
        acceptance = load_acceptance_state(cl_name, entry_id)
        read_state = load_read_state(cl_name, entry_id)

        total = 0
        accepted_count = 0
        read_count = 0

        seen: set[tuple[str, str]] = set()
        for sl in finished_lines:
            key = (sl.profile_name, sl.mentor_name)
            if key in seen:
                continue
            seen.add(key)

            output = ts_map.get(sl.timestamp)
            if output is None:
                continue

            for i in range(len(output.comments)):
                total += 1
                if acceptance.is_accepted(sl.profile_name, sl.mentor_name, i):
                    accepted_count += 1
                if read_state.is_read(sl.profile_name, sl.mentor_name, i):
                    read_count += 1

        if total == 0:
            return None

        return _MentorCommentStats(
            total=total,
            unread=max(0, total - read_count),
            accepted=min(accepted_count, total),
        )
    except Exception:
        log.debug(
            "Failed to compute mentor stats for %s",
            changespec.name,
            exc_info=True,
        )
        return None


def _mentor_stats_plain_text(stats: _MentorCommentStats) -> str:
    """Build plain text for mentor stats (for width calculation)."""
    parts: list[str] = []
    if stats.accepted > 0:
        parts.append(f"✓{stats.accepted}")
    if stats.unread > 0:
        parts.append(f"●{stats.unread}")
    parts.append(f"/{stats.total}")
    return "  " + " ".join(parts)


def _append_mentor_stats(text: Text, stats: _MentorCommentStats) -> None:
    """Append colored mentor comment stats to a Rich Text object."""
    text.append("  ", style="")
    has_prev = False
    if stats.accepted > 0:
        text.append(f"✓{stats.accepted}", style="bold #00AF00")
        has_prev = True
    if stats.unread > 0:
        if has_prev:
            text.append(" ", style="")
        text.append(f"●{stats.unread}", style="bold #FFAF00")
        has_prev = True
    if has_prev:
        text.append(" ", style="")
    text.append(f"/{stats.total}", style="#808080")


def calculate_entry_display_width(
    changespec: ChangeSpec,
    is_marked: bool,
    show_hideable: bool = False,
    show_submitted: bool = False,
    mentor_stats: _MentorCommentStats | None = None,
    hint_char: str | None = None,
) -> int:
    """Calculate display width of a ChangeSpec entry in terminal cells.

    Args:
        changespec: The ChangeSpec to measure
        is_marked: Whether this ChangeSpec is marked
        show_hideable: Whether hideable indicator is shown for reverted/archived
        show_submitted: Whether hideable indicator is shown for submitted
        mentor_stats: Optional mentor comment stats to include in width

    Returns:
        Width in terminal cells
    """
    indicator, _ = get_status_indicator(changespec)
    # Format: "◌ [✓] [{indicator}] {name} ({cl}) ✓n ●n /n"
    parts = []
    if hint_char is not None:
        parts.append(f"[{hint_char}] ")
    base_status = get_base_status(changespec.status)
    if show_hideable and base_status in ("Reverted", "Archived"):
        parts.append("◌ ")
    elif show_submitted and base_status == "Submitted":
        parts.append("◌ ")
    if is_marked:
        parts.append("[✓] ")
    parts.append(f"[{indicator}] ")
    parts.append(changespec.name)
    if changespec.cl:
        parts.append(f" ({changespec.cl})")
    if mentor_stats:
        parts.append(_mentor_stats_plain_text(mentor_stats))
    text = Text("".join(parts))
    return text.cell_len


def _get_status_letter_and_color(status: str) -> tuple[str, str]:
    """Map a status string to its letter and natural color.

    Args:
        status: The ChangeSpec status string

    Returns:
        Tuple of (letter, color)
    """
    if "..." in status:
        return "~", "#87AFFF"
    elif status.startswith("Draft"):
        return "D", "#FFD700"
    elif status.startswith("Ready"):
        return "R", "#87D700"
    elif status.startswith("Mailed"):
        return "M", "#00D787"
    elif status.startswith("Submitted"):
        return "S", "#00AF00"
    elif status.startswith("Reverted"):
        return "X", "#808080"
    elif status.startswith("Archived"):
        return "A", "#606060"
    return "W", "#87CEEB"


def get_status_indicator(changespec: ChangeSpec) -> tuple[str, str]:
    """Get a status indicator symbol and letter color for a ChangeSpec.

    Returns:
        Tuple of (indicator, letter_color)
    """
    status = changespec.status
    has_running = has_any_running_agent(changespec)
    has_process = has_any_running_process(changespec)
    has_error = has_any_error_suffix(changespec)
    letter, letter_color = _get_status_letter_and_color(status)

    # Build prefix components
    error_prefix = "!" if has_error else ""
    running_prefix = "@" if has_running else ""
    process_prefix = "$" if has_process else ""
    indicator = f"{error_prefix}{running_prefix}{process_prefix}{letter}"

    return indicator, letter_color


def row_signature(
    changespec: ChangeSpec,
    *,
    is_selected: bool,
    is_marked: bool,
    show_hideable: bool,
    show_submitted: bool,
    mentor_stats: _MentorCommentStats | None,
    hint_char: str | None,
) -> tuple[Any, ...]:
    """Compact key encoding everything that affects a row's rendered prompt."""
    indicator, _ = get_status_indicator(changespec)
    stats_tuple: tuple[int, int, int] | None = (
        (mentor_stats.total, mentor_stats.unread, mentor_stats.accepted)
        if mentor_stats is not None
        else None
    )
    return (
        changespec.name,
        changespec.cl,
        changespec.status,
        indicator,
        is_selected,
        is_marked,
        show_hideable,
        show_submitted,
        stats_tuple,
        hint_char,
    )


def format_changespec_option(
    changespec: ChangeSpec,
    *,
    is_selected: bool,
    is_marked: bool,
    show_hideable: bool = False,
    show_submitted: bool = False,
    mentor_stats: _MentorCommentStats | None = None,
    hint_char: str | None = None,
) -> Option:
    """Format a ChangeSpec as an option for display.

    Args:
        changespec: The ChangeSpec to format
        is_selected: Whether this is the currently selected item
        is_marked: Whether this item is marked
        show_hideable: Whether to show ◌ prefix for reverted/archived CLs
        show_submitted: Whether to show ◌ prefix for submitted CLs
        mentor_stats: Optional mentor comment stats to display
        hint_char: Optional jump hint character

    Returns:
        An Option for the OptionList
    """
    text = Text()
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    # Hideable indicator for reverted/archived CLs when visible
    base_status = get_base_status(changespec.status)
    if show_hideable and base_status in ("Reverted", "Archived"):
        text.append("◌ ", style="bold #FF5F87")
    elif show_submitted and base_status == "Submitted":
        text.append("◌ ", style="bold #00AF00")

    # Mark indicator (green checkmark)
    if is_marked:
        text.append("[✓] ", style="bold #00D700")

    # Status indicator
    indicator, letter_color = get_status_indicator(changespec)
    text.append("[", style=f"bold {letter_color}")
    for ch in indicator:
        text.append(ch, style=f"bold {_PREFIX_CHAR_COLORS.get(ch, letter_color)}")
    text.append("] ", style=f"bold {letter_color}")

    # Name
    name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    text.append(changespec.name, style=name_style)

    # CL number if present
    if changespec.cl:
        text.append(f" ({changespec.cl})", style="#569CD6 dim")

    # Mentor comment stats (latest commit)
    if mentor_stats:
        _append_mentor_stats(text, mentor_stats)

    return Option(text, id=changespec.name)
