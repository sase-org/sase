"""ChangeSpec list widget for the ace TUI."""

import logging
from dataclasses import dataclass
from datetime import datetime
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
from ..models.changespec_groups import (
    ChangeSpecGroupingMode,
    ChangeSpecGroupRow,
    build_changespec_tree,
)
from ..models.group_fold import GroupFoldRegistry, GroupKey
from ..util.trace import tui_trace
from ._changespec_list_banner import (
    CS_MIN_BANNER_WIDTH,
    banner_natural_width,
    format_changespec_banner_option,
)

#: Sentinel ``_row_entries`` value for banner rows.
_BANNER_ROW = -1

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
        """Message sent when selection changes.

        ``group_key`` is non-None when the selection target is a
        collapsed group banner row.  ``index`` then points at the first
        ChangeSpec in the group so the detail panel still has something
        to display, while callers that care about banner focus can read
        ``group_key`` to keep the heading-row state in sync.
        """

        def __init__(
            self,
            index: int,
            group_key: GroupKey | None = None,
        ) -> None:
            self.index = index
            self.group_key = group_key
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
        # Each rendered Option row maps back to a ChangeSpec index, or
        # ``_BANNER_ROW`` when the row is a group heading.  Populated by
        # both flat and grouped render paths so the selection event
        # handler can resolve clicks/highlights uniformly.
        self._row_entries: list[int] = []
        # Sparse map row_index -> ChangeSpecGroupRow for selectable
        # (collapsed) banner rows.  Expanded banners stay disabled and
        # skip the map entirely so they remain invisible to selection.
        self._banner_at_row: dict[int, ChangeSpecGroupRow] = {}
        # Banner key -> row index, so ``update_highlight`` can move the
        # cursor to a specific group banner without scanning the option
        # list.
        self._banner_row_by_key: dict[GroupKey, int] = {}
        # Active grouping mode for the current render.  Tracks which
        # path ``update_list`` took so test/inspection helpers can
        # branch on the most recent render.
        self._grouping_mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.FLAT

    def update_list(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        marked_indices: set[int] | None = None,
        hide_reverted: bool = True,
        hide_submitted: bool = True,
        jump_hints: dict[int, str] | None = None,
        grouping_mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.FLAT,
        fold_registry: GroupFoldRegistry | None = None,
        current_group_key: GroupKey | None = None,
        banner_jump_hints: dict[GroupKey, str] | None = None,
        now: datetime | None = None,
    ) -> None:
        """Update the list with new changespecs.

        Args:
            changespecs: List of ChangeSpecs to display
            current_idx: Index of currently selected ChangeSpec
            marked_indices: Set of indices that are marked
            hide_reverted: Whether reverted CLs are currently hidden
            hide_submitted: Whether submitted CLs are currently hidden
            jump_hints: Optional local row index -> hint character mapping
            grouping_mode: Which CL grouping mode to render.  ``FLAT``
                (default) preserves the historical one-row-per-CL render
                so existing tests stay byte-for-byte stable; the grouped
                modes interleave banner rows produced by
                :func:`build_changespec_tree`.
            fold_registry: Per-group collapse registry consulted by the
                tree builder.  Missing or empty registry renders every
                group expanded.  Ignored in ``FLAT``.
            current_group_key: When non-None and pointing at a banner
                row whose group is collapsed, highlight that banner
                instead of the CL row at ``current_idx``.
            banner_jump_hints: Group key -> hint character for collapsed
                banner rows (Phase 4 wires the producer side; the widget
                only needs to render whatever it is given).
            now: Reference time for ``BY_DATE`` bucketing.  Defaults to
                ``datetime.now()`` inside the tree builder.
        """
        with tui_trace("widget.changespec_list.update_list", count=len(changespecs)):
            self._update_list_impl(
                changespecs,
                current_idx,
                marked_indices=marked_indices,
                hide_reverted=hide_reverted,
                hide_submitted=hide_submitted,
                jump_hints=jump_hints,
                grouping_mode=grouping_mode,
                fold_registry=fold_registry,
                current_group_key=current_group_key,
                banner_jump_hints=banner_jump_hints,
                now=now,
            )

    def _update_list_impl(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        marked_indices: set[int] | None = None,
        hide_reverted: bool = True,
        hide_submitted: bool = True,
        jump_hints: dict[int, str] | None = None,
        grouping_mode: ChangeSpecGroupingMode = ChangeSpecGroupingMode.FLAT,
        fold_registry: GroupFoldRegistry | None = None,
        current_group_key: GroupKey | None = None,
        banner_jump_hints: dict[GroupKey, str] | None = None,
        now: datetime | None = None,
    ) -> None:
        self._programmatic_update = True
        self._marked_indices = marked_indices or set()
        self._changespecs = changespecs
        self._grouping_mode = grouping_mode
        # When not hiding, show ◌ prefix on the relevant CLs
        show_hideable = not hide_reverted
        show_submitted = not hide_submitted
        self.clear_options()
        self._option_idx_by_changespec_name = {}
        self._last_row_signature_by_idx = {}
        self._row_widths_by_idx = {}
        self._row_render_ctx = {}
        self._row_entries = []
        self._banner_at_row = {}
        self._banner_row_by_key = {}

        if grouping_mode is ChangeSpecGroupingMode.FLAT:
            self._render_flat(
                changespecs,
                current_idx,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                jump_hints=jump_hints,
            )
        else:
            self._render_grouped(
                changespecs,
                current_idx,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                jump_hints=jump_hints,
                grouping_mode=grouping_mode,
                fold_registry=fold_registry,
                current_group_key=current_group_key,
                banner_jump_hints=banner_jump_hints,
                now=now,
            )

    def _render_flat(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        *,
        show_hideable: bool,
        show_submitted: bool,
        jump_hints: dict[int, str] | None,
    ) -> None:
        """Original flat one-row-per-CL render path."""
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
            self._row_entries.append(i)
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

        try:
            if changespecs and 0 <= current_idx < len(changespecs):
                self.highlighted = current_idx
        finally:
            self._programmatic_update = False

    def _render_grouped(
        self,
        changespecs: list[ChangeSpec],
        current_idx: int,
        *,
        show_hideable: bool,
        show_submitted: bool,
        jump_hints: dict[int, str] | None,
        grouping_mode: ChangeSpecGroupingMode,
        fold_registry: GroupFoldRegistry | None,
        current_group_key: GroupKey | None,
        banner_jump_hints: dict[GroupKey, str] | None,
        now: datetime | None,
    ) -> None:
        """Render banner rows + CL rows for a non-FLAT grouping mode.

        The grouped path always does a full rebuild — the patch path
        guards against grouped renders by gating on
        ``option_count == len(self._changespecs)`` so a stale patch can
        never write to a row whose option index is offset by banner
        rows.
        """
        tree = build_changespec_tree(
            changespecs,
            mode=grouping_mode,
            fold_registry=fold_registry,
            now=now,
        )

        # First pass: format CL rows so we know the widest content.
        cs_options: dict[int, Option] = {}
        cs_widths: dict[int, int] = {}
        cs_signatures: dict[int, tuple[Any, ...]] = {}
        cs_render_ctx: dict[int, dict[str, Any]] = {}
        max_cs_width = 0
        for i, cs in enumerate(changespecs):
            is_marked = i in self._marked_indices
            stats = _compute_mentor_stats(cs)
            hint = (jump_hints or {}).get(i)
            cs_options[i] = self._format_changespec_option(
                cs,
                is_selected=(i == current_idx and current_group_key is None),
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            cs_widths[i] = _calculate_entry_display_width(
                cs,
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            max_cs_width = max(max_cs_width, cs_widths[i])
            cs_signatures[i] = _row_signature(
                cs,
                is_selected=(i == current_idx and current_group_key is None),
                is_marked=is_marked,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                mentor_stats=stats,
                hint_char=hint,
            )
            cs_render_ctx[i] = {
                "show_hideable": show_hideable,
                "show_submitted": show_submitted,
                "mentor_stats": stats,
            }

        # Banner width: at least CS_MIN_BANNER_WIDTH and at least the
        # widest CL row so the rule fully spans the panel.
        banner_min = max(CS_MIN_BANNER_WIDTH, max_cs_width)
        max_banner_natural = 0
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                banner_hint = (banner_jump_hints or {}).get(entry.group.group_key)
                max_banner_natural = max(
                    max_banner_natural,
                    banner_natural_width(entry.group, banner_hint),
                )
        banner_width = max(banner_min, max_banner_natural)

        # Walk the tree and emit Options.
        highlighted_row: int | None = None
        banner_seq = 0
        for entry in tree:
            if entry.kind == "group" and entry.group is not None:
                group = entry.group
                selectable = group.is_collapsed
                banner_hint = (
                    (banner_jump_hints or {}).get(group.group_key)
                    if selectable
                    else None
                )
                option = format_changespec_banner_option(
                    group,
                    width=banner_width,
                    sequence=banner_seq,
                    selectable=selectable,
                    hint_char=banner_hint,
                )
                banner_seq += 1
                row_index = len(self._row_entries)
                self.add_option(option)
                self._row_entries.append(_BANNER_ROW)
                if selectable:
                    self._banner_at_row[row_index] = group
                    self._banner_row_by_key[group.group_key] = row_index
                    if (
                        current_group_key is not None
                        and group.group_key == current_group_key
                        and highlighted_row is None
                    ):
                        highlighted_row = row_index
                continue

            if entry.changespec_idx is None:
                continue
            i = entry.changespec_idx
            row_index = len(self._row_entries)
            self.add_option(cs_options[i])
            self._row_entries.append(i)
            self._option_idx_by_changespec_name[changespecs[i].name] = i
            self._row_widths_by_idx[i] = cs_widths[i]
            self._last_row_signature_by_idx[i] = cs_signatures[i]
            self._row_render_ctx[i] = cs_render_ctx[i]
            if current_group_key is None and i == current_idx:
                highlighted_row = row_index

        _PADDING = 8
        optimal_width = max(max_cs_width, banner_width) + _PADDING
        self._target_width = optimal_width
        self.post_message(self.WidthChanged(optimal_width))

        try:
            if highlighted_row is not None:
                self.highlighted = highlighted_row
        finally:
            self._programmatic_update = False

    def _clear_programmatic_flag(self) -> None:
        """Clear programmatic update flag after event processing."""
        self._programmatic_update = False

    def update_highlight(
        self,
        current_idx: int,
        group_key: GroupKey | None = None,
    ) -> None:
        """Move the highlight without clearing/rebuilding options.

        Use this for j/k navigation where the item list hasn't changed,
        only the selection index.

        When *group_key* is non-None and matches a known collapsed
        banner row, the cursor jumps to that banner.  Otherwise the
        cursor moves to the row showing ``changespecs[current_idx]``,
        falling back to a clamped raw index for legacy flat callers
        that pre-date the row-map bookkeeping.
        """
        with tui_trace(
            "widget.changespec_list.update_highlight", count=self.option_count
        ):
            if self.option_count == 0:
                return
            if group_key is not None:
                row = self._banner_row_by_key.get(group_key)
                if row is not None:
                    self._programmatic_update = True
                    try:
                        self.highlighted = row
                    finally:
                        self._programmatic_update = False
                    return
            target_row: int | None = None
            if self._row_entries:
                # Find the option row that displays ``current_idx``.  In
                # flat mode this is identity; in grouped mode we may
                # need to step past banner rows.
                for row, entry in enumerate(self._row_entries):
                    if entry == current_idx:
                        target_row = row
                        break
            if target_row is None:
                target_row = min(max(current_idx, 0), self.option_count - 1)
            self._programmatic_update = True
            try:
                self.highlighted = target_row
            finally:
                self._programmatic_update = False

    def watch_highlighted(self, highlighted: int | None) -> None:
        """Suppress OptionHighlighted messages during programmatic updates."""
        from ..util.trace import trace_event

        if self._programmatic_update:
            trace_event(
                "widget.changespec_list.watch_highlighted.suppressed",
                highlighted=highlighted,
            )
            return
        trace_event(
            "widget.changespec_list.watch_highlighted",
            highlighted=highlighted,
        )
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
            self._programmatic_update = False

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
            index, group_key = self._resolve_row(event.option_index)
            self.post_message(self.SelectionChanged(index, group_key=group_key))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection (mouse click or Enter)."""
        if event.option_index is not None:
            index, group_key = self._resolve_row(event.option_index)
            self.post_message(self.SelectionChanged(index, group_key=group_key))

    def _resolve_row(self, option_index: int) -> tuple[int, GroupKey | None]:
        """Translate an OptionList row index to ``(changespec_idx, group_key)``.

        Selectable banner rows resolve to their group's first ChangeSpec
        plus the banner key so the caller can keep banner focus state
        in sync.  Non-banner rows resolve to their CL index with
        ``group_key=None``.

        When the row map hasn't been populated (e.g. tests that drive
        the OptionList directly without a prior render) the option
        index is returned verbatim with no group key.
        """
        if not (0 <= option_index < len(self._row_entries)):
            return (option_index, None)
        entry = self._row_entries[option_index]
        banner = self._banner_at_row.get(option_index)
        if banner is not None:
            first = banner.changespec_indices[0] if banner.changespec_indices else 0
            return (first, banner.group_key)
        if entry == _BANNER_ROW:
            # Expanded (non-selectable) banner row that somehow received
            # focus — fall through to the next CL row so the caller's
            # selection state stays meaningful.
            for j in range(option_index + 1, len(self._row_entries)):
                nxt = self._row_entries[j]
                if nxt != _BANNER_ROW:
                    return (nxt, None)
            for j in range(option_index - 1, -1, -1):
                prv = self._row_entries[j]
                if prv != _BANNER_ROW:
                    return (prv, None)
            return (0, None)
        return (entry, None)
