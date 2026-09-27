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
from textual.widgets import OptionList, Static

from ..actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    JumpHintMatchOutcome,
    match_jump_hint,
    normalize_jump_key,
)
from ..models.node_finder import NodeFinderSnapshot, NodeFinderView
from ..util.debounce import DetailPanelDebouncer
from ..util.pump_tasks import cancel_pump_free_tasks
from ..util.trace import tui_trace
from ._node_finder_modal_filtering import NodeFinderFilteringMixin
from ._node_finder_modal_options import NodeFinderOptionsMixin
from ._node_finder_modal_preview import NodeFinderPreviewMixin
from .base import FilterInput
from .node_finder_preview_loader import (
    NodeFinderPreviewCache,
    NodeFinderPreviewPayload,
    load_node_finder_preview,
)
from .node_finder_rendering import (
    layout_class_for_width,
    render_flash_slot,
    render_legend,
    render_mode_pill,
    render_scope_strip,
)

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.node_finder import AgentIdentity
    from textual.timer import Timer

_FLASH_S = 1.2
_PREVIEW_DELAY_S = 0.15
_PreviewLoader = Callable[["Agent"], NodeFinderPreviewPayload]


@dataclass(frozen=True, slots=True)
class NodeFinderResult:
    """Dismiss payload: a jump identity, or ``back=True`` for ``""``."""

    identity: AgentIdentity | None = None
    name: str = ""
    back: bool = False


class NodeFinderModal(
    NodeFinderFilteringMixin,
    NodeFinderOptionsMixin,
    NodeFinderPreviewMixin,
    ModalScreen[NodeFinderResult | None],
):
    """Large responsive Node Finder. Snapshot is fixed for the modal lifetime."""

    # Focus the list during compose so the open never transiently focuses
    # the query input (the app-wide ``"*"`` fallback) only to move focus
    # again in ``on_mount``. The steady state is unchanged: the list ends
    # focused either way, and ``on_mount`` still focuses it explicitly.
    AUTO_FOCUS = "#node-finder-list"

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
        # Per-modal filtered-view memo: the snapshot is fixed for the modal
        # lifetime and filtering is deterministic in (query, previous tokens),
        # so a repeated refilter (backspace, query toggle, Tab/Enter flush,
        # or the coalesced latest-wins worker firing twice) reuses the exact
        # same view object instead of rescanning thousands of rows. Keyed by
        # the previous view's tokens rather than its identity, so correctness
        # never depends on refinement monotonicity; a changed query always
        # misses and recomputes. Bounded and modal-local: entries die with
        # the modal, and live owner state is still read afresh on every open.
        self._view_cache: dict[tuple[str, tuple[str, ...] | None], NodeFinderView] = {}
        self._view = self._filtered_view("", None)
        self._last_options_key: tuple[object, ...] | None = None
        # Memoized per-view window guides (hint width plus sibling
        # closure); see ``NodeFinderOptionsMixin._window_guides``. The
        # entry only ever serves the live modal and dies with it.
        self._guides_view: NodeFinderView | None = None
        self._guides_width = 1
        self._guides_ends: set[int] = set()
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
        # The border title is set before mount so showing the screen never
        # schedules a second restyle for it after the first layout.
        container = Container(id="node-finder-container")
        container.border_title = "✦ Jump to Node ✦"
        # The responsive class is assigned before mount for the same
        # reason: adding it after mount re-applies the stylesheet across
        # the whole subtree. The app size at compose time equals the
        # screen size seen in ``on_mount`` (no resize can interleave the
        # mount sequence), and ``on_mount`` still reconciles a mismatch.
        self._layout_class = layout_class_for_width(self.app.size.width)
        if self._layout_class:
            self.add_class(self._layout_class)
        with container:
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
            # ``compose`` already assigned the class from the app width;
            # only a resize interleaved with the mount changes anything,
            # in which case this falls back to the exact resize path.
            desired_class = layout_class_for_width(self.size.width)
            if desired_class != self._layout_class:
                if self._layout_class:
                    self.remove_class(self._layout_class)
                self._layout_class = desired_class
                if desired_class:
                    self.add_class(desired_class)
            self._paint_chrome()
            self._rebuild_options(highlight=self._view.best_index)
            self.query_one("#node-finder-list", OptionList).focus()
            self._paint_preview()

    def on_unmount(self) -> None:
        if self._debouncer is not None:
            self._debouncer.cancel()
            self._debouncer = None
        if self._flash_timer is not None:
            self._flash_timer.stop()
            self._flash_timer = None
        # Invalidate any coalesced refilter still queued behind this screen.
        self._refilter_generation += 1
        self._pending_refilter_query = None
        # Invalidate in-flight Tier 1 loads so a late worker neither
        # repaints nor re-caches through the released snapshot below.
        self._preview_generation += 1
        cancel_pump_free_tasks(self)
        self._node_finder_preview_tasks.clear()
        self._release_per_open_state()

    def _release_per_open_state(self) -> None:
        """Drop every per-open reference so dismissal frees without the collector.

        A popped modal otherwise keeps its snapshot, views, and preview
        caches alive through the widget parent/child cycle (plus task and
        timer frames) until the next full collection, pushing ~10k objects
        per open into the old generation. Clearing here leaves only the
        small modal shell for the collector; the rows free by refcount the
        moment the screen is popped. The memo and the identical-rebuild
        skip only ever serve the live modal, so releasing them after
        dismissal loses nothing. Empty snapshot/view replacements (rather
        than ``None``) keep stray post-unmount reads total instead of
        raising; every producer path is still generation-guarded.
        """
        self._snapshot = NodeFinderSnapshot()
        self._view = NodeFinderView()
        self._view_cache.clear()
        self._tier0_cache.clear()
        self._cache = NodeFinderPreviewCache()
        self._last_options_key = None
        self._guides_view = None
        self._guides_width = 1
        self._guides_ends = set()
        self._window_base = 0
        self._window_end = 0
        self._pending = ""
        self._flash = ""

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
