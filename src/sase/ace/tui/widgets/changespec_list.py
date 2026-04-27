"""ChangeSpec list widget for the ace TUI."""

import logging
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
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
from ..util.trace import tui_trace

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


def _compute_mentor_stats(changespec: ChangeSpec) -> _MentorCommentStats | None:
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
        parts.append(f"\u2713{stats.accepted}")
    if stats.unread > 0:
        parts.append(f"\u25cf{stats.unread}")
    parts.append(f"/{stats.total}")
    return "  " + " ".join(parts)


def _append_mentor_stats(text: Text, stats: _MentorCommentStats) -> None:
    """Append colored mentor comment stats to a Rich Text object."""
    text.append("  ", style="")
    has_prev = False
    if stats.accepted > 0:
        text.append(f"\u2713{stats.accepted}", style="bold #00AF00")
        has_prev = True
    if stats.unread > 0:
        if has_prev:
            text.append(" ", style="")
        text.append(f"\u25cf{stats.unread}", style="bold #FFAF00")
        has_prev = True
    if has_prev:
        text.append(" ", style="")
    text.append(f"/{stats.total}", style="#808080")


def _calculate_entry_display_width(
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
    indicator, _ = _get_status_indicator(changespec)
    # Format: "◌ [✓] [{indicator}] {name} ({cl}) ✓n ●n /n"
    parts = []
    if hint_char is not None:
        parts.append(f"[{hint_char}] ")
    base_status = get_base_status(changespec.status)
    if show_hideable and base_status in ("Reverted", "Archived"):
        parts.append("\u25cc ")
    elif show_submitted and base_status == "Submitted":
        parts.append("\u25cc ")
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


def _get_status_indicator(changespec: ChangeSpec) -> tuple[str, str]:
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


def _row_signature(
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
    indicator, _ = _get_status_indicator(changespec)
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


class ChangeSpecList(OptionList):
    """Left sidebar showing list of ChangeSpecs."""

    class SelectionChanged(Message):
        """Message sent when selection changes."""

        def __init__(self, index: int) -> None:
            self.index = index
            super().__init__()

    class WidthChanged(Message):
        """Message sent when optimal width changes."""

        def __init__(self, width: int) -> None:
            self.width = width
            super().__init__()

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the ChangeSpec list."""
        super().__init__(**kwargs)
        self._changespecs: list[ChangeSpec] = []
        self._marked_indices: set[int] = set()
        self._programmatic_update: bool = False
        self._option_idx_by_changespec_name: dict[str, int] = {}
        self._last_row_signature_by_idx: dict[int, tuple[Any, ...]] = {}
        self._row_widths_by_idx: dict[int, int] = {}
        self._target_width: int = 0
        self._row_render_ctx: dict[int, dict[str, Any]] = {}

    def update_list(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        marked_indices: set[int] | None = None,
        hide_reverted: bool = True,
        hide_submitted: bool = True,
        jump_hints: dict[int, str] | None = None,
    ) -> None:
        """Update the list with new changespecs.

        Args:
            changespecs: List of ChangeSpecs to display
            current_idx: Index of currently selected ChangeSpec
            marked_indices: Set of indices that are marked
            hide_reverted: Whether reverted CLs are currently hidden
            hide_submitted: Whether submitted CLs are currently hidden
            jump_hints: Optional local row index -> hint character mapping
        """
        with tui_trace("widget.changespec_list.update_list", count=len(changespecs)):
            self._update_list_impl(
                changespecs,
                current_idx,
                marked_indices=marked_indices,
                hide_reverted=hide_reverted,
                hide_submitted=hide_submitted,
                jump_hints=jump_hints,
            )

    def _update_list_impl(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        marked_indices: set[int] | None = None,
        hide_reverted: bool = True,
        hide_submitted: bool = True,
        jump_hints: dict[int, str] | None = None,
    ) -> None:
        self._programmatic_update = True
        self._marked_indices = marked_indices or set()
        self._changespecs = changespecs
        # When not hiding, show ◌ prefix on the relevant CLs
        show_hideable = not hide_reverted
        show_submitted = not hide_submitted
        self.clear_options()
        self._option_idx_by_changespec_name = {}
        self._last_row_signature_by_idx = {}
        self._row_widths_by_idx = {}
        self._row_render_ctx = {}

        max_width = 0
        for i, cs in enumerate(changespecs):
            is_marked = i in self._marked_indices
            stats = _compute_mentor_stats(cs)
            hint = (jump_hints or {}).get(i)
            option = self._format_changespec_option(
                cs,
                is_selected=(i == current_idx),
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            self.add_option(option)
            width = _calculate_entry_display_width(
                cs,
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            max_width = max(max_width, width)
            self._option_idx_by_changespec_name[cs.name] = i
            self._row_widths_by_idx[i] = width
            self._last_row_signature_by_idx[i] = _row_signature(
                cs,
                is_selected=(i == current_idx),
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            self._row_render_ctx[i] = {
                "show_hideable": show_hideable,
                "show_submitted": show_submitted,
                "mentor_stats": stats,
            }

        # Add padding for border, scrollbar, visual comfort (~8 cells)
        _PADDING = 8
        optimal_width = max_width + _PADDING
        self._target_width = optimal_width
        self.post_message(self.WidthChanged(optimal_width))

        # Highlight the current item
        if changespecs and 0 <= current_idx < len(changespecs):
            self.highlighted = current_idx

        # Clear flag after event loop processes pending events
        self.call_later(self._clear_programmatic_flag)

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

    def update_highlight(self, current_idx: int) -> None:
        """Move the highlight without clearing/rebuilding options.

        Use this for j/k navigation where the item list hasn't changed,
        only the selection index.
        """
        with tui_trace(
            "widget.changespec_list.update_highlight", count=self.option_count
        ):
            if self.option_count == 0:
                return
            target_idx = min(max(current_idx, 0), self.option_count - 1)
            self._programmatic_update = True
            self.highlighted = target_idx
            self.call_later(self._clear_programmatic_flag)

    def watch_highlighted(self, highlighted: int | None) -> None:
        """Suppress OptionHighlighted messages during programmatic updates."""
        if self._programmatic_update:
            return
        super().watch_highlighted(highlighted)

    def patch_changespec_row(
        self,
        idx: int,
        changespec: ChangeSpec,
        *,
        selected: bool,
        marked: bool,
        hint: str | None = None,
    ) -> bool:
        """Replace one ChangeSpec's Option in place when shape didn't change.

        Returns ``True`` when the patch landed; ``False`` when the caller
        must fall back to a full :meth:`update_list` rebuild — the row
        index drifted, the alignment width grew past the cached target,
        or no prior full render captured the per-row context.
        """
        with tui_trace("widget.changespec_list.patch_changespec_row", idx=idx):
            return self._patch_changespec_row_impl(
                idx,
                changespec,
                selected=selected,
                marked=marked,
                hint=hint,
            )

    def _patch_changespec_row_impl(
        self,
        idx: int,
        changespec: ChangeSpec,
        *,
        selected: bool,
        marked: bool,
        hint: str | None,
    ) -> bool:
        if not (0 <= idx < len(self._changespecs)):
            return False
        ctx = self._row_render_ctx.get(idx)
        if ctx is None:
            return False
        # Row-count drift: refuse to patch when the underlying option list
        # no longer matches the cached size.
        if self.option_count != len(self._changespecs):
            return False

        existing = self._changespecs[idx]
        if existing.name != changespec.name:
            return False
        # The option_id is the changespec name — keep the cached idx map
        # honest by refusing to patch an entry whose name moved index.
        if self._option_idx_by_changespec_name.get(changespec.name) != idx:
            return False

        show_hideable: bool = ctx["show_hideable"]
        show_submitted: bool = ctx["show_submitted"]
        stats = _compute_mentor_stats(changespec)

        new_width = _calculate_entry_display_width(
            changespec,
            is_marked=marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
        )
        # Container width was posted at full-rebuild time as
        # ``_target_width = max_content_width + _PADDING``. A patched row
        # whose content stays within ``_target_width`` fits the parent
        # panel; only fall back when growth would exceed the cached
        # panel width and require a fresh WidthChanged message.
        if self._target_width and new_width > self._target_width:
            return False

        new_option = self._format_changespec_option(
            changespec,
            is_selected=selected,
            is_marked=marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
        )

        self._programmatic_update = True
        try:
            self.replace_option_prompt_at_index(idx, new_option.prompt)
        except (AttributeError, IndexError):
            return False
        finally:
            self.call_later(self._clear_programmatic_flag)

        self._changespecs[idx] = changespec
        if marked:
            self._marked_indices.add(idx)
        else:
            self._marked_indices.discard(idx)
        self._row_widths_by_idx[idx] = new_width
        self._row_render_ctx[idx]["mentor_stats"] = stats
        self._last_row_signature_by_idx[idx] = _row_signature(
            changespec,
            is_selected=selected,
            is_marked=marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
        )
        return True

    def _format_changespec_option(
        self,
        changespec: ChangeSpec,
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
            text.append("\u25cc ", style="bold #FF5F87")
        elif show_submitted and base_status == "Submitted":
            text.append("\u25cc ", style="bold #00AF00")

        # Mark indicator (green checkmark)
        if is_marked:
            text.append("[✓] ", style="bold #00D700")

        # Status indicator
        indicator, letter_color = _get_status_indicator(changespec)
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

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Handle option highlight (keyboard navigation)."""
        if self._programmatic_update:
            return  # Skip events from programmatic updates
        if event.option_index is not None:
            self.post_message(self.SelectionChanged(event.option_index))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if event.option_index is not None:
            self.post_message(self.SelectionChanged(event.option_index))
