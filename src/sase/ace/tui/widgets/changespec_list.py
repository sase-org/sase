"""ChangeSpec list widget for the ace TUI."""

from datetime import datetime
from typing import Any

from textual.message import Message
from textual.widgets import OptionList

from ...changespec import ChangeSpec
from ..models.changespec_groups import (
    ChangeSpecGroupingMode,
    ChangeSpecGroupRow,
)
from ..models.group_fold import GroupFoldRegistry, GroupKey
from ..util.trace import tui_trace
from ._changespec_list_helpers import (
    calculate_entry_display_width,
    compute_mentor_stats,
    format_changespec_option,
    get_status_indicator,
    row_signature,
)
from ._changespec_list_render import _BANNER_ROW, render_flat, render_grouped

# Re-exported for backward compatibility with tests / external callers
# that imported these names from this module before the split.
_get_status_indicator = get_status_indicator
__all__ = ["ChangeSpecList", "_BANNER_ROW", "_get_status_indicator"]


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
            render_flat(
                self,
                changespecs,
                current_idx,
                show_hideable=show_hideable,
                show_submitted=show_submitted,
                jump_hints=jump_hints,
            )
        else:
            render_grouped(
                self,
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
        stats = compute_mentor_stats(changespec)

        new_width = calculate_entry_display_width(
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

        new_option = format_changespec_option(
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
        self._last_row_signature_by_idx[idx] = row_signature(
            changespec,
            is_selected=selected,
            is_marked=marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
        )
        return True

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
