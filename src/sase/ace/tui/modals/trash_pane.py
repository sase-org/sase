"""Reusable Trash pane for the tabbed Prompts overlay.

Trash shows drafts deliberately discarded from Stash, newest-deleted-first
with the deletion age visible. It shares the Stash row/preview treatment
(shortcut gutter, project chip, bundle chip, one-line preview) while keeping
its verb, pin, and mark rules distinct: there is no pin edit, restore marks
use the orchid ``✓``, and permanent-deletion marks use a red ``✗``.

The pane never touches the store directly. ``tab``/``a`` stage rows for
restore to Stash and ``enter`` posts :class:`TrashRestoreRequested`; the
overlay stays open and the host repaints authoritatively. ``d``/``D`` stage
rows for permanent deletion and ``enter`` posts :class:`PurgeRequested`;
the host must show an explicit confirmation (see :func:`purge_confirm_text`)
before applying it. Only purging every remaining row dismisses via
:class:`TrashPane.Selected`, since there is nothing left to display.
``ctrl+y`` posts :class:`TrashCopyRequested` for the host to copy. Unknown
IDs and repeated transitions are no-ops: :meth:`TrashPane.apply_snapshot`
drops staged marks for IDs absent from the authoritative snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from sase.ace.tui.prompt_stash_entries import entry_prompt_segments
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.util.xprompt_syntax import highlight_prompt_text
from sase.core.prompt_stash_wire import (
    PromptStashEntryWire,
    PromptStashTrashRecordWire,
)
from sase.project_display_names import ProjectDisplaySnapshot

from ._prompt_stash_preview import PromptStashPreviewPane, tagified_stash_text
from .base import OptionListNavigationMixin
from .prompt_stash_row import (
    DEFAULT_STASH_PREVIEW_WIDTH,
    INDEX_KEYS,
    append_shortcut,
    prompt_stash_preview_width_for_list_content,
    trash_row_age,
    trash_row_label,
)

_TRASH_LIST_ID = "trash-list"

_SPLIT_PANE_MIN_TERMINAL_WIDTH = 110


@dataclass
class TrashActionResult:
    """Outcome of a Trash pane interaction that dismisses the overlay.

    Only the purge-everything path dismisses (no rows remain to display);
    every other apply posts a request message and keeps the overlay open.
    ``restore_ids`` move back to Stash; ``purge_ids`` are permanently
    deleted. Order is irrelevant.
    """

    restore_ids: list[str] = field(default_factory=list)
    purge_ids: list[str] = field(default_factory=list)


class TrashRestoreRequested(Message, namespace="trash_pane"):
    """Posted when ``enter`` confirms a restore selection.

    The overlay stays open; the host moves these ids back to Stash and
    repaints both panes from the returned store outcome.
    """

    def __init__(self, entry_ids: list[str]) -> None:
        super().__init__()
        self.entry_ids = entry_ids


class PurgeRequested(Message, namespace="trash_pane"):
    """Posted when ``enter`` confirms a purge selection leaving rows.

    The host must show an explicit confirmation before applying it; the
    overlay stays open and the host repaints from the store outcome.
    """

    def __init__(self, entry_ids: list[str]) -> None:
        super().__init__()
        self.entry_ids = entry_ids


class TrashCopyRequested(Message, namespace="trash_pane"):
    """Posted when ``ctrl+y`` requests a copy of the highlighted row."""

    def __init__(self, entry: PromptStashEntryWire) -> None:
        super().__init__()
        self.entry = entry


TRASH_BINDINGS: list[Any] = [
    *OptionListNavigationMixin.NAVIGATION_BINDINGS,
    Binding("tab", "toggle_restore", "Restore", priority=True),
    ("a", "toggle_all", "All"),
    ("d", "mark_purge", "Delete"),
    ("D", "mark_purge_all", "Delete All"),
    Binding("ctrl+y", "copy_row", "Copy", priority=True),
    Binding("ctrl+d", "scroll_preview_down", "Preview Down", priority=True),
    Binding("ctrl+u", "scroll_preview_up", "Preview Up", priority=True),
    *[
        Binding(key, f"restore_index({idx})", f"Restore #{idx + 1}", show=False)
        for idx, key in enumerate(INDEX_KEYS)
    ],
]


def sort_trash_records(
    records: list[PromptStashTrashRecordWire],
) -> list[PromptStashTrashRecordWire]:
    """Return trash records newest-deleted-first.

    ISO-8601 deletion timestamps sort lexicographically. The sort is stable,
    so equal timestamps keep batch input order — the tie break the store
    contract requires (batch input/order, then ID).
    """
    return sorted(records, key=lambda r: r.trashed_at, reverse=True)


def trash_empty_text(*, trash_limit: int, has_stash_rows: bool = False) -> str:
    """Return the empty-Trash explanation for the given configuration."""
    if trash_limit == 0:
        return (
            "Recovery is disabled (trash_limit is 0). "
            "Discarded drafts are permanently deleted."
        )
    return (
        "Discarded drafts appear here. Stash d moves a draft to Trash."
        if has_stash_rows
        else "Discarded drafts appear here after Stash d moves them to Trash."
    )


def purge_confirm_text(
    marked_ids: list[str],
    records: list[PromptStashTrashRecordWire],
) -> str:
    """Return the explicit purge confirmation message for staged rows."""
    count = len(marked_ids)
    noun = "draft" if count == 1 else "drafts"
    lines = [
        f"Permanently delete {count} {noun}? This cannot be undone.",
    ]
    by_id = {record.entry.id: record for record in records}
    for entry_id in marked_ids[:5]:
        record = by_id.get(entry_id)
        if record is None:
            continue
        preview = record.entry.text.splitlines()
        first = next((line.strip() for line in preview if line.strip()), "(empty)")
        if len(first) > 60:
            first = f"{first[:59]}…"
        lines.append(f"  • {first}")
    if count > 5:
        lines.append(f"  … and {count - 5} more")
    return "\n".join(lines)


class TrashPane(OptionListNavigationMixin, Widget):
    """Reusable trash list/preview pane for the tabbed Prompts overlay.

    The overlay shell owns the heading and footer; this pane renders only the
    list/preview panels and reports restores/purges as request messages
    instead of touching the store.
    """

    class Selected(Message):
        """Posted when the trash pane resolves to a dismissing outcome."""

        def __init__(self, result: TrashActionResult | None) -> None:
            super().__init__()
            self.result = result

    # Re-export the trash messages so hosts can reference one home.
    TrashRestoreRequested = TrashRestoreRequested
    PurgeRequested = PurgeRequested
    TrashCopyRequested = TrashCopyRequested

    # Option-list DOM id for OptionListNavigationMixin (j/k and friends).
    _option_list_id = _TRASH_LIST_ID

    BINDINGS = TRASH_BINDINGS

    def __init__(
        self,
        records: list[PromptStashTrashRecordWire],
        *,
        project_display_snapshot: ProjectDisplaySnapshot | None = None,
        trash_limit: int = 20,
    ) -> None:
        super().__init__()
        self._records: list[PromptStashTrashRecordWire] = sort_trash_records(
            list(records)
        )
        self._project_display_snapshot = (
            project_display_snapshot or ProjectDisplaySnapshot()
        )
        self._trash_limit = trash_limit
        self._prompt_counts = {
            record.entry.id: len(entry_prompt_segments(record.entry))
            for record in self._records
        }
        self._restore: set[str] = set()
        self._purge: set[str] = set()
        self._highlight_cache: dict[str, Text] = {}
        self._preview_debouncer: DetailPanelDebouncer | None = None
        self._refreshing_options = False
        self._narrow = True
        self._last_preview_width_budget = DEFAULT_STASH_PREVIEW_WIDTH

    def dismiss(self, result: TrashActionResult | None = None) -> None:
        """Translate screen-style confirm into a bubbled selection."""
        self.post_message(TrashPane.Selected(result))

    # -- snapshot ----------------------------------------------------------

    @property
    def record_ids(self) -> list[str]:
        """Return the visible trash ids, newest-deleted-first."""
        return [record.entry.id for record in self._records]

    def apply_snapshot(self, records: list[PromptStashTrashRecordWire]) -> None:
        """Repaint from an authoritative store snapshot.

        Unknown or repeated transitions are no-ops: staged marks for IDs
        absent from the snapshot are dropped, surviving marks are kept, and
        the highlight follows its row when it is still present.
        """
        highlighted_id = self._highlighted_entry_id()
        self._records = sort_trash_records(list(records))
        live = {record.entry.id for record in self._records}
        self._restore.intersection_update(live)
        self._purge.intersection_update(live)
        self._prompt_counts = {
            record.entry.id: len(entry_prompt_segments(record.entry))
            for record in self._records
        }
        for cached_id in list(self._highlight_cache):
            if cached_id not in live:
                del self._highlight_cache[cached_id]
        self._refresh_rows()
        self._repaint_after_snapshot(highlighted_id)

    def apply_store_failure(self) -> None:
        """Repaint truthfully after a failed write.

        Rows and staged marks are left untouched: the failure changed
        nothing, so the visible state is already the truth. The repaint
        only heals a highlight or preview left stale by the attempt.
        """
        self._refresh_rows()
        entry = self._highlighted_record()
        if entry is not None:
            self._paint_preview(entry.entry.id)
        else:
            self._show_empty_preview()

    # -- layout ------------------------------------------------------------

    def _hint_text(self) -> str:
        return (
            "Enter: restore to Stash · 1-9/0 restore · a all · j/k move · esc/q · ^d/u\n"
            "tab ✓ restore · d permanently delete row · D permanently delete all · ^y copy"
        )

    def _empty_text(self) -> str:
        return trash_empty_text(trash_limit=self._trash_limit)

    def compose(self) -> ComposeResult:
        with Vertical(id="trash-pane-body"):
            with Horizontal(id="trash-panels"):
                with Vertical(id="trash-list-panel"):
                    yield OptionList(*self._build_options(), id=_TRASH_LIST_ID)
                yield PromptStashPreviewPane(id="trash-preview-pane")

    def on_mount(self) -> None:
        self._preview_debouncer = DetailPanelDebouncer(self.app)  # type: ignore[attr-defined]
        self._set_narrow_mode(self.app.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)  # type: ignore[attr-defined]
        try:
            self.query_one(f"#{_TRASH_LIST_ID}", OptionList).focus()  # type: ignore[attr-defined]
        except Exception:
            pass
        if self._records:
            self._paint_preview(self._records[0].entry.id)
        else:
            self._show_empty_preview()
        self.call_after_refresh(self._refresh_rows_for_current_width)  # type: ignore[attr-defined]

    def on_unmount(self) -> None:
        if self._preview_debouncer is not None:
            self._preview_debouncer.cancel()

    def on_resize(self, event: events.Resize) -> None:
        self._set_narrow_mode(event.size.width < _SPLIT_PANE_MIN_TERMINAL_WIDTH)
        self.call_after_refresh(self._refresh_rows_for_current_width)  # type: ignore[attr-defined]

    def focus_trash_list(self) -> None:
        """Focus the trash list, falling back silently when not mounted."""
        try:
            self.query_one(f"#{_TRASH_LIST_ID}", OptionList).focus()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _build_options(self, *, preview_width: int | None = None) -> list[Option]:
        if preview_width is None:
            preview_width = self._last_preview_width_budget
        self._last_preview_width_budget = preview_width
        options: list[Option] = []
        for idx, record in enumerate(self._records):
            label = Text(no_wrap=True, overflow="ellipsis")
            shortcut = INDEX_KEYS[idx] if idx < len(INDEX_KEYS) else None
            append_shortcut(label, shortcut)
            label.append_text(
                trash_row_label(
                    record,
                    marked_for_restore=record.entry.id in self._restore,
                    marked_for_purge=record.entry.id in self._purge,
                    trashed_age=trash_row_age(record),
                    prompt_count=self._prompt_counts[record.entry.id],
                    preview_width=preview_width,
                    project_display_snapshot=self._project_display_snapshot,
                )
            )
            options.append(Option(label, id=str(idx)))
        return options

    # -- selection state ---------------------------------------------------

    def _highlighted_index_and_record(
        self,
    ) -> tuple[int, PromptStashTrashRecordWire] | None:
        try:
            option_list = self.query_one(f"#{_TRASH_LIST_ID}", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None or not 0 <= highlighted < len(self._records):
            return None
        return highlighted, self._records[highlighted]

    def _highlighted_record(self) -> PromptStashTrashRecordWire | None:
        highlighted = self._highlighted_index_and_record()
        return highlighted[1] if highlighted is not None else None

    def _highlighted_entry_id(self) -> str | None:
        record = self._highlighted_record()
        return record.entry.id if record is not None else None

    def _refresh_rows(self) -> None:
        try:
            option_list = self.query_one(f"#{_TRASH_LIST_ID}", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        highlighted = option_list.highlighted
        self._refreshing_options = True
        try:
            option_list.clear_options()
            option_list.add_options(self._build_options())
            if self._records and highlighted is not None:
                option_list.highlighted = min(highlighted, len(self._records) - 1)
        finally:
            self._refreshing_options = False

    def _resolve_preview_width_budget(self) -> int:
        if self._narrow:
            return DEFAULT_STASH_PREVIEW_WIDTH
        try:
            option_list = self.query_one(f"#{_TRASH_LIST_ID}", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return DEFAULT_STASH_PREVIEW_WIDTH
        width = option_list.scrollable_content_region.width
        if width <= 0:
            width = option_list.content_size.width
        if width <= 0:
            width = option_list.size.width
        return prompt_stash_preview_width_for_list_content(width)

    def _refresh_rows_for_current_width(self) -> None:
        preview_width = self._resolve_preview_width_budget()
        if preview_width == self._last_preview_width_budget:
            return
        self._last_preview_width_budget = preview_width
        self._refresh_rows()

    def _set_narrow_mode(self, narrow: bool) -> None:
        self._narrow = narrow
        try:
            container = self.query_one("#trash-pane-body", Vertical)  # type: ignore[attr-defined]
        except Exception:
            return
        container.set_class(narrow, "-narrow")

    def _repaint_after_snapshot(self, highlighted_id: str | None) -> None:
        if not self._records:
            self._show_empty_preview()
            return
        new_index: int | None = None
        if highlighted_id is not None:
            for idx, record in enumerate(self._records):
                if record.entry.id == highlighted_id:
                    new_index = idx
                    break
        if new_index is None:
            new_index = 0
        try:
            option_list = self.query_one(f"#{_TRASH_LIST_ID}", OptionList)  # type: ignore[attr-defined]
        except Exception:
            return
        option_list.highlighted = new_index
        self._paint_preview(self._records[new_index].entry.id)

    # -- preview -----------------------------------------------------------

    def _show_empty_preview(self) -> None:
        try:
            pane = self.query_one(PromptStashPreviewPane)  # type: ignore[attr-defined]
        except Exception:
            return
        pane.show_placeholder(self._empty_text())

    def _schedule_preview(self, entry_id: str) -> None:
        if self._preview_debouncer is None:
            self._paint_preview(entry_id)
            return
        self._preview_debouncer.schedule(
            lambda: self._paint_preview_if_current(entry_id)
        )

    def _paint_preview_if_current(self, entry_id: str) -> None:
        record = self._highlighted_record()
        if record is not None and record.entry.id == entry_id:
            self._paint_preview(entry_id)

    def _paint_preview(self, entry_id: str) -> None:
        record = next(
            (item for item in self._records if item.entry.id == entry_id), None
        )
        if record is None:
            self._show_empty_preview()
            return
        try:
            pane = self.query_one(PromptStashPreviewPane)  # type: ignore[attr-defined]
        except Exception:
            return
        highlighted = self._highlight_cache.get(record.entry.id)
        if highlighted is None:
            highlighted = highlight_prompt_text(tagified_stash_text(record.entry.text))
            self._highlight_cache[record.entry.id] = highlighted
        pane.show_entry(
            record.entry,
            prompt_count=self._prompt_counts[record.entry.id],
            highlighted_body=highlighted,
            project_display_snapshot=self._project_display_snapshot,
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Debounce the expensive preview paint while navigation stays instant."""
        if self._refreshing_options or event.option is None or event.option.id is None:
            return
        try:
            index = int(event.option.id)
        except ValueError:
            return
        if 0 <= index < len(self._records):
            self._schedule_preview(self._records[index].entry.id)

    # -- actions -----------------------------------------------------------

    def action_scroll_preview_down(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(1)  # type: ignore[attr-defined]

    def action_scroll_preview_up(self) -> None:
        self.query_one(PromptStashPreviewPane).scroll_half_page(-1)  # type: ignore[attr-defined]

    def action_toggle_restore(self) -> None:
        record = self._highlighted_record()
        if record is None:
            return
        if record.entry.id in self._restore:
            self._restore.discard(record.entry.id)
        else:
            self._restore.add(record.entry.id)
            self._purge.discard(record.entry.id)
        self._refresh_rows()

    def action_toggle_all(self) -> None:
        entry_ids = {record.entry.id for record in self._records}
        if not entry_ids:
            return
        if entry_ids <= self._restore:
            self._restore.difference_update(entry_ids)
        else:
            self._restore.update(entry_ids)
            self._purge.difference_update(entry_ids)
        self._refresh_rows()

    def action_mark_purge(self) -> None:
        record = self._highlighted_record()
        if record is None:
            return
        if record.entry.id in self._purge:
            self._purge.discard(record.entry.id)
        else:
            self._purge.add(record.entry.id)
            self._restore.discard(record.entry.id)
        self._refresh_rows()

    def action_mark_purge_all(self) -> None:
        entry_ids = {record.entry.id for record in self._records}
        if not entry_ids:
            return
        self._purge.update(entry_ids)
        self._restore.difference_update(entry_ids)
        self._refresh_rows()

    def action_copy_row(self) -> None:
        record = self._highlighted_record()
        if record is None:
            return
        self.post_message(TrashCopyRequested(record.entry))

    def action_restore_index(self, index: int) -> None:
        if not 0 <= index < len(self._records):
            return
        self.post_message(TrashRestoreRequested([self._records[index].entry.id]))

    def action_confirm(self) -> None:
        restore_ids = [
            record.entry.id
            for record in self._records
            if record.entry.id in self._restore
        ]
        purge_ids = [
            record.entry.id
            for record in self._records
            if record.entry.id in self._purge
        ]
        if restore_ids:
            self.post_message(TrashRestoreRequested(restore_ids))
        if purge_ids and not restore_ids and len(purge_ids) == len(self._records):
            # Every remaining row is staged for purge: nothing would be left
            # to display, so dismiss and let the host confirm + apply.
            self.dismiss(TrashActionResult(purge_ids=purge_ids))
            return
        if purge_ids:
            self.post_message(PurgeRequested(purge_ids))
        if not restore_ids and not purge_ids:
            record = self._highlighted_record()
            if record is not None:
                self.post_message(TrashRestoreRequested([record.entry.id]))

    def on_option_list_option_selected(self, _event: OptionList.OptionSelected) -> None:
        # ``enter`` (and click) confirms: restore the staged set, or just the
        # highlighted row when nothing is staged. The overlay stays open.
        self.action_confirm()


__all__ = [
    "PurgeRequested",
    "TRASH_BINDINGS",
    "TrashActionResult",
    "TrashCopyRequested",
    "TrashPane",
    "TrashRestoreRequested",
    "purge_confirm_text",
    "sort_trash_records",
    "trash_empty_text",
]
