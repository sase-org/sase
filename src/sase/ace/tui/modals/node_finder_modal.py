"""Agents-tab Node Finder modal: tree list, HINTS/SEARCH modes, two-tier preview."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.events import Key, Resize
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    JumpHintMatchOutcome,
    match_jump_hint,
    normalize_jump_key,
)
from ..models.node_finder import (
    NodeFinderRow,
    NodeFinderSnapshot,
    filter_node_finder,
    next_jumpable_index,
)
from ..util.debounce import DetailPanelDebouncer
from ..util.pump_tasks import cancel_pump_free_tasks, spawn_pump_free_task
from ..util.trace import tui_trace
from .base import FilterInput
from .node_finder_preview import render_node_finder_preview
from .node_finder_preview_loader import (
    NodeFinderPreviewCache,
    NodeFinderPreviewPayload,
    load_node_finder_preview,
    render_tier1,
    tier1_source,
)
from .node_finder_rendering import (
    EMPTY_PREVIEW,
    empty_match_label,
    hint_column_width,
    last_child_indices,
    layout_class_for_width,
    render_flash_slot,
    render_legend,
    render_mode_pill,
    render_row_prompt,
    render_scope_strip,
    show_status_column,
)

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.node_finder import AgentIdentity
    from textual.timer import Timer

_FLASH_S = 1.2
_PREVIEW_DELAY_S = 0.15
_PreviewLoader = Callable[["Agent"], NodeFinderPreviewPayload]

#: Maximum rows materialized in the ``OptionList``. Broad results keep
#: every row in the view (hints, cursor, and jump targets span the whole
#: list) while only this window around the highlight becomes widgets, so
#: a 2,000-row rebuild stays inside the refilter budget. Cursor motion
#: re-centers the window when it steps outside.
_OPTION_WINDOW_SIZE = 64


@dataclass(frozen=True, slots=True)
class NodeFinderResult:
    """Dismiss payload: a jump identity, or ``back=True`` for ``""``."""

    identity: AgentIdentity | None = None
    name: str = ""
    back: bool = False


class NodeFinderModal(ModalScreen[NodeFinderResult | None]):
    """Large responsive Node Finder. Snapshot is fixed for the modal lifetime."""

    BINDINGS = [
        Binding("tab", "toggle_search", "Search", priority=True, show=False),
        Binding("shift+tab", "toggle_search", "Search", priority=True, show=False),
        Binding("ctrl+n", "cursor_next", "Next", priority=True, show=False),
        Binding("ctrl+p", "cursor_prev", "Previous", priority=True, show=False),
        Binding("down", "cursor_next", "Next", priority=True, show=False),
        Binding("up", "cursor_prev", "Previous", priority=True, show=False),
        Binding("pgdown", "preview_down", "Preview down", priority=True, show=False),
        Binding("pgup", "preview_up", "Preview up", priority=True, show=False),
    ]

    def __init__(
        self,
        snapshot: NodeFinderSnapshot,
        has_back: bool = False,
        preview_loader: _PreviewLoader | None = None,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._has_back = has_back
        self._preview_loader = preview_loader or load_node_finder_preview
        self._view = filter_node_finder(snapshot, "")
        self._search_mode = False
        self._pending = ""
        self._flash = ""
        self._flash_timer: Timer | None = None
        self._refilter_generation = 0
        self._pending_refilter_query: str | None = None
        self._layout_class = ""
        self._highlighting = False
        self._preview_generation = 0
        self._cache = NodeFinderPreviewCache()
        self._tier0_cache: dict[tuple[object, ...], Text] = {}
        self._window_base = 0
        self._window_end = 0
        self._debouncer: DetailPanelDebouncer | None = None
        self._node_finder_preview_tasks: set[asyncio.Task[None]] = set()

    def compose(self) -> ComposeResult:
        with Container(id="node-finder-container"):
            yield Static("✦ Jump to Node ✦", id="node-finder-title")
            with Horizontal(id="node-finder-top"):
                yield FilterInput(
                    placeholder="Tab or / to search nodes…",
                    id="node-finder-query",
                )
                yield Static(id="node-finder-pill")
                yield Static(id="node-finder-scope")
            with Horizontal(id="node-finder-body"):
                yield OptionList(id="node-finder-list")
                with VerticalScroll(id="node-finder-preview-scroll"):
                    yield Static(id="node-finder-preview")
            with Horizontal(id="node-finder-footer"):
                yield Static(id="node-finder-legend")
                yield Static(id="node-finder-flash")

    def on_mount(self) -> None:
        with tui_trace("node_finder.open"):
            self._debouncer = DetailPanelDebouncer(self.app, delay_s=_PREVIEW_DELAY_S)
            self._layout_class = layout_class_for_width(self.size.width)
            if self._layout_class:
                self.add_class(self._layout_class)
            self.query_one(
                "#node-finder-container", Container
            ).border_title = "✦ Jump to Node ✦"
            self._paint_chrome()
            self._rebuild_options(highlight=self._view.best_index)
            self.query_one("#node-finder-list", OptionList).focus()
            self._paint_preview()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
        if self._flash_timer is not None:
            self._flash_timer.stop()
        # Invalidate any coalesced refilter still queued behind this screen.
        self._refilter_generation += 1
        self._pending_refilter_query = None
        cancel_pump_free_tasks(self)

    def on_resize(self, event: Resize) -> None:
        desired = layout_class_for_width(event.size.width)
        if desired == self._layout_class:
            return
        if self._layout_class:
            self.remove_class(self._layout_class)
        self._layout_class = desired
        if desired:
            self.add_class(desired)
        self._rebuild_options(highlight=self._highlighted_view_index())

    def on_key(self, event: Key) -> None:
        if self._search_mode:
            if event.key == "escape":
                event.prevent_default()
                event.stop()
                self._enter_hints()
                return
            if event.key == "enter":
                event.prevent_default()
                event.stop()
                self._jump_highlighted()
                return
            event.stop()
            return
        event.prevent_default()
        event.stop()
        key = normalize_jump_key(event.key, event.character)
        if key in {"escape", "backspace"}:
            if self._pending:
                self._pending = ""
                self._refresh_hint_gutters()
                self._paint_chrome()
            elif key == "escape":
                self.dismiss(None)
            return
        if key in {"slash", "/"}:
            self._enter_search()
            return
        if key in {"quotation_mark", '"'}:
            self._jump_back()
            return
        if key == "enter":
            self._jump_highlighted()
            return
        if key == "ctrl+u":
            return
        if key in JUMP_HINT_CHARS:
            self._handle_hint(key)
            return
        label = event.character if event.character else event.key
        self._set_flash(f"no hint ‹{label}›")

    def action_toggle_search(self) -> None:
        if self._search_mode:
            self._enter_hints()
        else:
            self._enter_search()

    def action_cursor_next(self) -> None:
        self._move_cursor(1)

    def action_cursor_prev(self) -> None:
        self._move_cursor(-1)

    def action_preview_down(self) -> None:
        self._preview_scroll().scroll_relative(y=1, animate=False)

    def action_preview_up(self) -> None:
        self._preview_scroll().scroll_relative(y=-1, animate=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "node-finder-query":
            return
        self._schedule_refilter(event.value)

    def _schedule_refilter(self, value: str) -> None:
        """Arm a latest-wins refilter; the keystroke callback stays thin.

        Rapid keystrokes supersede one another via the generation guard, so a
        burst collapses to a single list rebuild for the final query. Tab and
        Enter flush through :meth:`_flush_pending_refilter` first. The worker
        runs on the next message tick (no added delay); staleness is decided
        by generation, so no timer handle needs cancelling.
        """
        self._refilter_generation += 1
        generation = self._refilter_generation
        self._pending_refilter_query = value
        self.call_next(self._fire_scheduled_refilter, value, generation)

    def _fire_scheduled_refilter(self, query: str, generation: int) -> None:
        if self._pending_refilter_query == query:
            self._pending_refilter_query = None
        self._apply_refilter(query, generation)

    def _apply_refilter(self, query: str, generation: int) -> None:
        if generation != self._refilter_generation:
            return  # Superseded by a newer keystroke; latest wins.
        if not self.is_mounted:
            return
        with tui_trace("node_finder.filter"):
            self._view = filter_node_finder(self._snapshot, query, previous=self._view)
            self._pending = ""
            self._rebuild_options(highlight=self._view.best_index)
            self._paint_chrome()
            self._paint_preview()

    def _flush_pending_refilter(self) -> None:
        """Run any coalesced refilter now so Tab/Enter see the latest list.

        Bumping the generation first drops the still-queued scheduled worker
        when it fires.
        """
        if self._pending_refilter_query is None:
            return
        query = self._pending_refilter_query
        self._pending_refilter_query = None
        self._refilter_generation += 1
        self._apply_refilter(query, self._refilter_generation)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "node-finder-query":
            return
        self._jump_highlighted()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id != "node-finder-list":
            return
        if event.option_index is None:
            self._set_flash("No matching node")
            return
        self._jump_index(event.option_index + self._window_base)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._highlighting or event.option_list.id != "node-finder-list":
            return
        self._paint_preview()

    def _enter_search(self) -> None:
        self._search_mode = True
        self._pending = ""
        self._paint_chrome()
        self._refresh_hint_gutters()
        self.query_one("#node-finder-query", FilterInput).focus()

    def _enter_hints(self) -> None:
        self._flush_pending_refilter()
        self._search_mode = False
        self._pending = ""
        self._paint_chrome()
        self._refresh_hint_gutters()
        self._list().focus()

    def _handle_hint(self, key: str) -> None:
        match = match_jump_hint(self._view.hint_to_identity, self._pending, key)
        if match.outcome is JumpHintMatchOutcome.COMPLETE and match.target is not None:
            self._pending = ""
            self._jump_identity(match.target)
            return
        if match.outcome is JumpHintMatchOutcome.PENDING:
            self._pending = match.prefix
            self._refresh_hint_gutters()
            self._paint_chrome()
            return
        self._set_flash(f"no hint ‹{key}›")

    def _highlighted_view_index(self) -> int | None:
        """Return the highlighted view row, translating the option offset."""
        highlighted = self._list().highlighted
        if highlighted is None:
            return None
        return self._window_base + highlighted

    def _move_cursor(self, direction: int) -> None:
        if not self._view.rows:
            return
        current = self._highlighted_view_index()
        if current is None or not (0 <= current < len(self._view.rows)):
            current = self._view.best_index if self._view.best_index is not None else 0
        nxt = next_jumpable_index(self._view, current, direction)
        self._set_highlighted(nxt)
        self._paint_preview()

    def _jump_back(self) -> None:
        if self._has_back:
            self.dismiss(NodeFinderResult(back=True))
            return
        self._set_flash("no jump history")

    def _jump_highlighted(self) -> None:
        self._flush_pending_refilter()
        highlighted = self._highlighted_view_index()
        if highlighted is None:
            self._set_flash("No matching node")
            return
        self._jump_index(highlighted)

    def _jump_index(self, index: int | None) -> None:
        if index is None or not (0 <= index < len(self._view.rows)):
            self._set_flash("No matching node")
            return
        row = self._view.rows[index]
        if not row.jumpable or index in self._view.context or row.identity is None:
            self._set_flash("No matching node")
            return
        self.dismiss(NodeFinderResult(identity=row.identity, name=row.name))

    def _jump_identity(self, identity: AgentIdentity) -> None:
        for row in self._view.rows:
            if row.identity == identity:
                self.dismiss(NodeFinderResult(identity=identity, name=row.name))
                return
        self._set_flash("No matching node")

    def _window_for(self, highlight: int | None) -> tuple[int, int]:
        """Return the ``[base, end)`` view range materialized as options.

        The window centers on the highlight when the view overflows it;
        small views materialize whole. Every view row stays reachable:
        hints span the full view and cursor motion re-centers the window.
        """
        total = len(self._view.rows)
        if total <= _OPTION_WINDOW_SIZE:
            return (0, total)
        target = highlight
        if target is None or not (0 <= target < total):
            target = self._view.best_index if self._view.best_index is not None else 0
        start = min(
            max(0, target - _OPTION_WINDOW_SIZE // 2), total - _OPTION_WINDOW_SIZE
        )
        return (start, start + _OPTION_WINDOW_SIZE)

    def _rebuild_options(self, *, highlight: int | None) -> None:
        option_list = self._list()
        hint_width = hint_column_width(self._view)
        status = show_status_column(self._layout_class)
        # One sibling-closure pass shared by every row's tree guides; computing
        # it per row would make a rebuild O(rows^2). Guides span the full
        # view even though only the window becomes widgets.
        guide_ends = last_child_indices(self._view.rows)
        resolved: int | None
        if highlight is not None and 0 <= highlight < len(self._view.rows):
            resolved = highlight
        else:
            resolved = self._view.best_index
        options: list[Option] = []
        if not self._view.rows:
            options.append(
                Option(
                    empty_match_label(self._view.query),
                    id="__empty__",
                    disabled=True,
                )
            )
            self._window_base = 0
            self._window_end = 0
        else:
            base, end = self._window_for(resolved)
            self._window_base = base
            self._window_end = end
            for index in range(base, end):
                row = self._view.rows[index]
                disabled = (
                    not row.jumpable
                    or index in self._view.context
                    or row.identity is None
                )
                options.append(
                    Option(
                        render_row_prompt(
                            self._view,
                            index,
                            search_mode=self._search_mode,
                            pending=self._pending,
                            show_status=status,
                            hint_width=hint_width,
                            last_child=guide_ends,
                        ),
                        id=f"nf-{index}",
                        disabled=disabled,
                    )
                )
        option_list.clear_options()
        option_list.add_options(options)
        if resolved is not None and self._window_base <= resolved < self._window_end:
            self._set_highlighted(resolved)

    def _refresh_hint_gutters(self) -> None:
        if not self.is_mounted:
            return
        self._rebuild_options(highlight=self._highlighted_view_index())

    def _set_highlighted(self, index: int) -> None:
        if not (self._window_base <= index < self._window_end):
            # Outside the materialized window: re-center first so every
            # cursor step stays reachable.
            self._rebuild_options(highlight=index)
            return
        option_list = self._list()
        self._highlighting = True
        try:
            option_list.highlighted = index - self._window_base
        finally:
            self._highlighting = False

    def _paint_chrome(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#node-finder-pill", Static).update(
            render_mode_pill(self._search_mode)
        )
        self.query_one("#node-finder-scope", Static).update(
            render_scope_strip(
                self._snapshot, self._view, search_mode=self._search_mode
            )
        )
        self.query_one("#node-finder-legend", Static).update(
            render_legend(search_mode=self._search_mode)
        )
        self.query_one("#node-finder-flash", Static).update(
            render_flash_slot(pending=self._pending, flash=self._flash)
        )

    def _paint_preview(self) -> None:
        with tui_trace("node_finder.preview"):
            preview = self.query_one("#node-finder-preview", Static)
            row = self._current_row()
            if row is None:
                preview.update(Text(EMPTY_PREVIEW, style="dim"))
                return
            payload = None
            source = tier1_source(row, self._snapshot)
            if source is not None:
                payload = self._cache.get(source.identity)
            preview.update(self._compose_preview(row, payload))
            self._schedule_tier1(row)

    def _tier0_cache_key(self, row: NodeFinderRow) -> tuple[object, ...]:
        """Return the Tier 0 cache key for *row*.

        The snapshot (and its query) is fixed for the modal lifetime and
        reasons never change within it, so the Tier 0 text depends only on
        which node or header the row shows.
        """
        identity = row.identity
        if identity is not None:
            return ("node", identity)
        return (
            "header",
            row.role.value,
            row.name,
            row.group_label,
            row.panel_key,
        )

    def _compose_preview(
        self,
        row: NodeFinderRow,
        payload: NodeFinderPreviewPayload | None,
    ) -> Text:
        key = self._tier0_cache_key(row)
        base = self._tier0_cache.get(key)
        if base is None:
            base = render_node_finder_preview(row, self._snapshot, self._snapshot.query)
            self._tier0_cache[key] = base
        if payload is None:
            return base
        cutoff = base.plain.rfind("PROMPT")
        combined = Text()
        if cutoff > 0:
            combined.append_text(base[:cutoff])
        combined.append_text(render_tier1(payload))
        return combined

    def _schedule_tier1(self, row: NodeFinderRow) -> None:
        source = tier1_source(row, self._snapshot)
        self._preview_generation += 1
        generation = self._preview_generation
        if source is None or self._debouncer is None:
            return
        identity = source.identity

        def _kick() -> None:
            spawn_pump_free_task(
                self,
                self._load_tier1(identity, generation),
                name="node-finder-preview",
                registry_attr="_node_finder_preview_tasks",
            )

        self._debouncer.schedule(_kick)

    async def _load_tier1(self, identity: AgentIdentity, generation: int) -> None:
        agent = self._agent_for(identity)
        if agent is None:
            return
        payload = await asyncio.to_thread(self._preview_loader, agent)
        if generation != self._preview_generation:
            return
        current = self._current_row()
        if current is None or current.identity != identity:
            return
        self._cache.put(payload)
        self.query_one("#node-finder-preview", Static).update(
            self._compose_preview(current, payload)
        )

    def _agent_for(self, identity: AgentIdentity) -> Agent | None:
        for row in self._snapshot.rows:
            if row.identity == identity:
                return row.agent
        return None

    def _current_row(self) -> NodeFinderRow | None:
        if not self.is_mounted:
            return None
        highlighted = self._highlighted_view_index()
        if highlighted is None or not (0 <= highlighted < len(self._view.rows)):
            return None
        return self._view.rows[highlighted]

    def _set_flash(self, message: str) -> None:
        self._flash = message
        if self._flash_timer is not None:
            self._flash_timer.stop()
        if self.is_mounted:
            self._flash_timer = self.set_timer(_FLASH_S, self._clear_flash)
            self._paint_chrome()

    def _clear_flash(self) -> None:
        self._flash = ""
        self._flash_timer = None
        self._paint_chrome()

    def _list(self) -> OptionList:
        return self.query_one("#node-finder-list", OptionList)

    def _preview_scroll(self) -> VerticalScroll:
        return self.query_one("#node-finder-preview-scroll", VerticalScroll)


__all__ = ["NodeFinderModal", "NodeFinderResult"]
