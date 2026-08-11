"""Pure helpers for the Patch list widget.

Houses mentor-stat aggregation, status-indicator computation, row signature
hashing, width calculation, and the per-row Option formatter.  Kept free
of widget state so :mod:`patch_list` can stay focused on the
``OptionList`` subclass.
"""

import logging
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from sase.project_display_names import humanize_cl_name

from ..patch_status import patch_status_glyph
from ...patch import (
    PR_ORIGIN_EXTERNAL,
    PR_ORIGIN_SASE,
    Patch,
    get_base_status,
    has_any_error_suffix,
    has_any_running_agent,
    has_any_running_process,
    normalize_pr_origin,
)
from ...mentor_output import (
    load_acceptance_state,
    load_mentor_outputs_for_commit,
    load_read_state,
)
from ...query.highlighting import PR_ORIGIN_VALUE_STYLES

log = logging.getLogger(__name__)

_PREFIX_CHAR_COLORS: dict[str, str] = {
    "!": "#FF5F5F",  # Red for error
    "@": "#FFAF00",  # Orange for running agent
    "$": "#D7AF00",  # Darker yellow for running process
}


# ── Mentor comment stats ────────────────────────────────────────────────


@dataclass
class _MentorCommentStats:
    """Aggregate mentor comment stats for display in the Patch list."""

    total: int
    unread: int
    accepted: int


def compute_mentor_stats(patch: Patch) -> _MentorCommentStats | None:
    """Compute mentor comment stats for the latest commit entry.

    Returns None if there are no finished mentors with comments.
    """
    if not patch.mentors:
        return None
    try:
        latest_entry = max(patch.mentors, key=lambda e: e.entry_id)
        if not latest_entry.status_lines:
            return None

        finished_statuses = {"PASSED", "COMMENTED", "FAILED"}
        finished_lines = [
            sl for sl in latest_entry.status_lines if sl.status in finished_statuses
        ]
        if not finished_lines:
            return None

        timestamps = {sl.timestamp for sl in finished_lines if sl.timestamp}
        cl_name = patch.name
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

            output = ts_map.get(sl.timestamp) if sl.timestamp else None
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
            patch.name,
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


def _pr_origin_chip(patch: Patch) -> tuple[str, str] | None:
    """Return the (text, style) origin chip for a row, or None to omit it.

    The chip is the row's second, independent PR signal ("who created
    that PR?") — distinct from the PR badge itself, which already shows
    that a remote review exists. ``sase`` origin is the expected case and
    renders nothing; a chip on every row would be noise.
    """
    if not patch.pr_url:
        return None
    origin = normalize_pr_origin(patch.pr_origin)
    if origin == PR_ORIGIN_SASE:
        return None
    if origin == PR_ORIGIN_EXTERNAL:
        return "external", PR_ORIGIN_VALUE_STYLES["external"]
    return "origin?", PR_ORIGIN_VALUE_STYLES["unknown"]


def _pr_origin_chip_plain_text(patch: Patch) -> str:
    """Build plain text for the origin chip (for width calculation)."""
    chip = _pr_origin_chip(patch)
    return f"  {chip[0]}" if chip is not None else ""


def calculate_entry_display_width(
    patch: Patch,
    is_marked: bool,
    show_hideable: bool = False,
    show_submitted: bool = False,
    mentor_stats: _MentorCommentStats | None = None,
    hint_char: str | None = None,
) -> int:
    """Calculate display width of a Patch entry in terminal cells.

    Args:
        patch: The Patch to measure
        is_marked: Whether this Patch is marked
        show_hideable: Whether hideable indicator is shown for reverted/archived
        show_submitted: Whether hideable indicator is shown for submitted
        mentor_stats: Optional mentor comment stats to include in width

    Returns:
        Width in terminal cells
    """
    indicator, _ = get_status_indicator(patch)
    # Format: "◌ [✓] [{indicator}] {name} ({cl}) ✓n ●n /n"
    parts = []
    if hint_char is not None:
        parts.append(f"[{hint_char}] ")
    base_status = get_base_status(patch.status)
    if show_hideable and base_status in ("Reverted", "Archived"):
        parts.append("◌ ")
    elif show_submitted and base_status == "Submitted":
        parts.append("◌ ")
    if is_marked:
        parts.append("[✓] ")
    parts.append(f"[{indicator}] ")
    parts.append(humanize_cl_name(patch.name))
    if patch.pr_url:
        parts.append(f" ({patch.pr_url})")
        parts.append(_pr_origin_chip_plain_text(patch))
    if mentor_stats:
        parts.append(_mentor_stats_plain_text(mentor_stats))
    text = Text("".join(parts))
    return text.cell_len


def get_status_indicator(patch: Patch) -> tuple[str, str]:
    """Get a status indicator symbol and letter color for a Patch.

    Returns:
        Tuple of (indicator, letter_color)
    """
    status = patch.status
    has_running = has_any_running_agent(patch)
    has_process = has_any_running_process(patch)
    has_error = has_any_error_suffix(patch)
    letter, letter_color = patch_status_glyph(status)

    # Build prefix components
    error_prefix = "!" if has_error else ""
    running_prefix = "@" if has_running else ""
    process_prefix = "$" if has_process else ""
    indicator = f"{error_prefix}{running_prefix}{process_prefix}{letter}"

    return indicator, letter_color


def row_signature(
    patch: Patch,
    *,
    is_selected: bool,
    is_marked: bool,
    show_hideable: bool,
    show_submitted: bool,
    mentor_stats: _MentorCommentStats | None,
    hint_char: str | None,
) -> tuple[Any, ...]:
    """Compact key encoding everything that affects a row's rendered prompt."""
    indicator, _ = get_status_indicator(patch)
    stats_tuple: tuple[int, int, int] | None = (
        (mentor_stats.total, mentor_stats.unread, mentor_stats.accepted)
        if mentor_stats is not None
        else None
    )
    return (
        humanize_cl_name(patch.name),
        patch.pr_url,
        normalize_pr_origin(patch.pr_origin),
        patch.status,
        indicator,
        is_selected,
        is_marked,
        show_hideable,
        show_submitted,
        stats_tuple,
        hint_char,
    )


def format_patch_option(
    patch: Patch,
    *,
    is_selected: bool,
    is_marked: bool,
    show_hideable: bool = False,
    show_submitted: bool = False,
    mentor_stats: _MentorCommentStats | None = None,
    hint_char: str | None = None,
) -> Option:
    """Format a Patch as an option for display.

    Args:
        patch: The Patch to format
        is_selected: Whether this is the currently selected item
        is_marked: Whether this item is marked
        show_hideable: Whether to show ◌ prefix for reverted/archived Patches
        show_submitted: Whether to show ◌ prefix for submitted Patches
        mentor_stats: Optional mentor comment stats to display
        hint_char: Optional jump hint character

    Returns:
        An Option for the OptionList
    """
    text = Text()
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    # Hideable indicator for reverted/archived Patches when visible
    base_status = get_base_status(patch.status)
    if show_hideable and base_status in ("Reverted", "Archived"):
        text.append("◌ ", style="bold #FF5F87")
    elif show_submitted and base_status == "Submitted":
        text.append("◌ ", style="bold #00AF00")

    # Mark indicator (green checkmark)
    if is_marked:
        text.append("[✓] ", style="bold #00D700")

    # Status indicator
    indicator, letter_color = get_status_indicator(patch)
    text.append("[", style=f"bold {letter_color}")
    for ch in indicator:
        text.append(ch, style=f"bold {_PREFIX_CHAR_COLORS.get(ch, letter_color)}")
    text.append("] ", style=f"bold {letter_color}")

    # Name
    name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    text.append(humanize_cl_name(patch.name), style=name_style)

    # PR number if present
    if patch.pr_url:
        text.append(f" ({patch.pr_url})", style="#569CD6 dim")
        chip = _pr_origin_chip(patch)
        if chip is not None:
            chip_text, chip_style = chip
            text.append(f"  {chip_text}", style=chip_style)

    # Mentor comment stats (latest commit)
    if mentor_stats:
        _append_mentor_stats(text, mentor_stats)

    return Option(text, id=patch.name)
