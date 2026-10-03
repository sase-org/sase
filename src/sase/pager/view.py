"""``PagerView``: the mountable per-document pager widget.

A ``PagerView`` owns everything per-document that ``PagerScreen`` used to
own directly: the composed body, label layer, trail, search controller,
goto prompt, history, diff, time band and syntax state, plus the chrome
rows around the scrollable body. ``PagerScreen`` hosts one (later two)
of these views and routes keys and footer ownership to the focused one.

This split is pixel-inert by construction: a single unfocused-frameless
view composes exactly the rows the old screen composed, and only the
focused view may paint the shared footer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from rich.rule import Rule
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets.vim_search_controller import VimSearchController
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import (
    ComposedBody,
    ReadingAnchor,
    reading_anchor_at_row,
    row_for_reading_anchor,
)
from sase.pager._line_mark import LineMark
from sase.pager._screen_actions import PagerActionMixin
from sase.pager._screen_actions_resolve import DanglingRefKey
from sase.pager._screen_body import PagerBodyMixin
from sase.pager._screen_chrome import PagerChromeMixin
from sase.pager._screen_diff import PagerDiffMixin
from sase.pager._screen_goto import PagerGotoMixin
from sase.pager._screen_history import PagerHistoryMixin
from sase.pager._screen_search import PagerSearchMixin
from sase.pager._screen_syntax import PagerSyntaxMixin
from sase.pager._screen_time_band import PagerTimeBandMixin
from sase.pager._screen_timeline import PagerTimelineMixin
from sase.pager._screen_trail import PagerTrailMixin
from sase.pager._screen_widgets import PagerBody, PagerBodyScroll
from sase.pager.app import (
    AttachedTargetHandler,
    ResolveRef,
    ViewPendingAction,
)
from sase.pager.document import PagerDocument
from sase.pager.trail import PagerTrailEntry


class _PagerViewHost(Protocol):
    """What a ``PagerView`` needs from its hosting screen.

    Views never import ``PagerScreen``; the screen satisfies this
    protocol structurally.
    """

    def paint_footer(self, view: PagerView, legend: object) -> None:
        """Paint *legend* into the shared footer when *view* is focused."""
        ...

    def close_view(self, view: PagerView, *, trail_exhausted: bool = False) -> None:
        """Close *view*; dismiss the pager when the last view closes."""
        ...

    def focus_view(self, view: PagerView) -> None:
        """Move logical focus to *view* (a no-op when already focused)."""
        ...

    def focus_other_view(self, source: PagerView) -> None:
        """Focus the armed (else MRU) other pane (a no-op when single)."""
        ...

    def show_in_other_view(
        self,
        source: PagerView,
        document: PagerDocument,
        line: int | None,
        end_line: int | None = None,
    ) -> None:
        """Open *document* in the captured ``ctrl+w`` target pane.

        With one pane this opens a split (stacked when it fits, else side
        by side); focus never moves.
        """
        ...


@dataclass(frozen=True, slots=True)
class PagerViewSeed:
    """A faithful clone payload for opening a split pane.

    The new view shares the same document but owns independent trail,
    history, syntax-prepared and dangling-ref state, so stepping versions
    in one pane never moves the other.
    """

    document: PagerDocument
    reading_anchor: ReadingAnchor | None = None
    goto_mark: LineMark | None = None
    back_trail: tuple[PagerTrailEntry, ...] = ()
    forward_trail: tuple[PagerTrailEntry, ...] = ()
    history_states: tuple[tuple[str, object], ...] = ()
    history_supported: tuple[tuple[str, bool], ...] = ()
    history_view_sticky: object | None = None
    syntax_prepared: tuple[tuple[tuple[str, str | None], object], ...] = ()
    syntax_attempted: tuple[tuple[str, str | None], ...] = ()
    dangling_refs: tuple[tuple[object, str], ...] = ()


class PagerView(  # type: ignore[misc]
    PagerTimeBandMixin,
    PagerHistoryMixin,
    PagerDiffMixin,
    PagerTimelineMixin,
    PagerBodyMixin,
    PagerActionMixin,
    PagerTrailMixin,
    PagerChromeMixin,
    PagerSearchMixin,
    PagerGotoMixin,
    PagerSyntaxMixin,
    Vertical,
):
    """One mountable document view: body, chrome rows, and key handling.

    The mixin stack and MRO match what ``PagerScreen`` used to carry, so
    per-document behavior is unchanged — only the host moved out.
    """

    def __init__(
        self,
        document: PagerDocument,
        *,
        links_enabled: bool = True,
        attached_handlers: Mapping[str, AttachedTargetHandler] | None = None,
        resolve_ref: ResolveRef,
        syntax_enabled: bool = True,
        refresh_document_fn: Callable[[], PagerDocument | None] | None = None,
    ) -> None:
        """Own one `PagerDocument` inside a hosting ``PagerScreen``.

        ``attached_handlers`` is stored by reference, never copied, so a
        host that registers handlers after construction (ACE commit
        targets) still reaches this view. ``resolve_ref`` is the already
        resolved callable the screen evaluated at construction.
        """
        super().__init__()
        self.document = document
        self.links_enabled = links_enabled
        self.syntax_enabled = syntax_enabled
        self._attached_handlers: Mapping[str, AttachedTargetHandler] = (
            {} if attached_handlers is None else attached_handlers
        )
        self._resolve_ref = resolve_ref
        self._refresh_document_fn = refresh_document_fn
        self._refresh_in_flight = False
        self._body: ComposedBody | None = None
        self._body_width: int | None = None
        self._last_composed_width: int | None = None
        self._body_generation = 0
        self._label_layer: PagerLabelLayer | None = None
        self._label_pending_prefix = ""
        self._label_window_scope: LabelWindowScope | None = None
        self._last_activated_label: PagerLabel | None = None
        self._pending_action: ViewPendingAction = "follow"
        self._dangling_refs: dict[DanglingRefKey, str] = {}
        self._resolve_generation = 0
        self._search = VimSearchController(self)
        self._back_trail: list[PagerTrailEntry] = []
        self._forward_trail: list[PagerTrailEntry] = []
        self._trail_render_signature: object | None = None
        self._footer_status: str | None = None
        self._pane_framed = False
        self._pane_focused = True
        self._pane_preview = False
        self._split_anchor: ReadingAnchor | None = None
        self._chrome_signature: object | None = None
        self._init_goto_state()
        self._init_syntax_state()
        self._init_history_state()
        self._init_diff_state()
        self._init_time_band_state()

    @property
    def pager_host(self) -> _PagerViewHost:
        """Return the hosting screen cast to the view-host protocol."""
        return self.screen  # type: ignore[return-value]

    def _chrome_height(self) -> int:
        """Height the trail/time chrome budgets degrade against.

        Single-pane rendering historically measured the whole screen
        (footer rows included); keep measuring it so budgets stay
        byte-identical. Framed split panes compact per-pane chrome
        deliberately against their own height.
        """
        if getattr(self, "_pane_framed", False):
            try:
                return max(int(self.size.height), 1)
            except Exception:
                pass
        try:
            return max(int(self.screen.size.height), 1)
        except Exception:
            return max(int(self.size.height), 1)

    def set_pane_role(
        self, *, framed: bool, focused: bool, preview: bool = False
    ) -> None:
        """Apply the host's split role to this pane.

        Unfocused panes drop their label badges (like
        ``links_enabled=False``) and cancel transient input; refocused
        panes rebuild their labels. Called for every layout change, so it
        is idempotent and safe before mount. ``preview`` lifts an
        unfocused pane's frame while ``ctrl+w`` is armed; every layout
        change passes the default and clears it.
        """
        framed = bool(framed)
        focused = bool(focused)
        preview = bool(preview)
        if (
            framed == self._pane_framed
            and focused == self._pane_focused
            and preview == self._pane_preview
        ):
            return
        was_focused = self._pane_focused
        self._pane_framed = framed
        self._pane_focused = focused
        self._pane_preview = preview
        if framed and not focused and was_focused:
            self._cancel_transient_input()
        try:
            if not self.is_mounted:
                return
        except Exception:
            return
        if framed and not focused:
            self._label_layer = PagerLabelLayer(
                labels=(),
                hint_to_label_index={},
                labels_by_section=tuple(() for _section in self.document.sections),
                target_count=0,
                mode="document",
            )
            # Force a body recompose so the dropped badges leave the paint;
            # without it the old badge spans stay visible until the next
            # recompose even though the layer is already empty.
            self._body_width = None
            try:
                self._ensure_body()
            except Exception:
                pass
            self._chrome_signature = None
            try:
                self._update_subject()
                self._update_footer()
            except Exception:
                pass
            return
        # Focused (or single) panes repaint labels and chrome.
        self._body_width = None
        try:
            self._ensure_body()
        except Exception:
            pass
        self._chrome_signature = None
        try:
            self._update_trail()
            self._update_footer()
            self._update_subject()
        except Exception:
            pass

    def set_pane_preview(self, preview: bool) -> None:
        """Lift (or drop) this pane's frame for an armed ``ctrl+w`` target.

        A light path beside :meth:`set_pane_role`: badges, trails, and
        transient input are untouched, only the frame border repaints at
        preview strength. Safe before mount.
        """
        preview = bool(preview)
        if preview == getattr(self, "_pane_preview", False):
            return
        self._pane_preview = preview
        if not getattr(self, "_pane_framed", False):
            return
        try:
            if not self.is_mounted:
                return
        except Exception:
            return
        self._chrome_signature = None
        try:
            self._update_subject()
        except Exception:
            pass

    def _cancel_transient_input(self) -> None:
        """Drop prefix, arms, goto prompt and typing search on focus loss."""
        self._label_pending_prefix = ""
        try:
            self._pending_action = "follow"
        except Exception:
            pass
        try:
            if getattr(self, "_goto_active", False):
                self._close_goto_prompt()
        except Exception:
            pass
        try:
            if getattr(self._search, "mode", "off") == "typing":
                self._search.exit(restore_scroll=False, refresh=False)
        except Exception:
            pass
        try:
            self._footer_status = None
        except Exception:
            pass

    def split_seed(self) -> PagerViewSeed:
        """Capture a faithful clone payload for opening a split pane."""
        anchor: ReadingAnchor | None = None
        try:
            body = self._body
            if body is not None:
                anchor = reading_anchor_at_row(body, int(self._body_scroll().scroll_y))
        except Exception:
            anchor = None
        try:
            back = tuple(self._back_trail)
        except Exception:
            back = ()
        try:
            forward = tuple(self._forward_trail)
        except Exception:
            forward = ()
        history_states: list[tuple[str, object]] = []
        try:
            states = dict(getattr(self, "_history_states", {}) or {})
            import dataclasses

            for identity, state in states.items():
                try:
                    clone = dataclasses.replace(
                        state,
                        body_cache=dict(getattr(state, "body_cache", {}) or {}),
                        comparison_cache=dict(
                            getattr(state, "comparison_cache", {}) or {}
                        ),
                        expanded_folds=set(
                            getattr(state, "expanded_folds", set()) or set()
                        ),
                    )
                except Exception:
                    clone = state
                history_states.append((identity, clone))
        except Exception:
            history_states = []
        try:
            supported = tuple(
                (key, bool(value))
                for key, value in dict(
                    getattr(self, "_history_supported", {}) or {}
                ).items()
            )
        except Exception:
            supported = ()
        try:
            sticky = getattr(self, "_history_view_sticky", None)
        except Exception:
            sticky = None
        try:
            prepared = tuple(
                (key, value)
                for key, value in dict(
                    getattr(self, "_syntax_prepared", {}) or {}
                ).items()
            )
        except Exception:
            prepared = ()
        try:
            attempted = tuple(set(getattr(self, "_syntax_attempted", set()) or set()))
        except Exception:
            attempted = ()
        try:
            dangling = tuple(
                (key, value)
                for key, value in dict(
                    getattr(self, "_dangling_refs", {}) or {}
                ).items()
            )
        except Exception:
            dangling = ()
        return PagerViewSeed(
            document=self.document,
            reading_anchor=anchor,
            goto_mark=getattr(self, "_goto_mark", None),
            back_trail=back,
            forward_trail=forward,
            history_states=tuple(history_states),
            history_supported=supported,
            history_view_sticky=sticky,
            syntax_prepared=prepared,
            syntax_attempted=attempted,
            dangling_refs=dangling,
        )

    def apply_split_seed(self, seed: PagerViewSeed) -> None:
        """Install *seed* before mount; the anchor scrolls after layout."""
        self.document = seed.document
        self._back_trail = list(seed.back_trail)
        self._forward_trail = list(seed.forward_trail)
        try:
            self._goto_mark = seed.goto_mark
        except Exception:
            pass
        try:
            self._history_states = dict(seed.history_states)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            self._history_supported = dict(seed.history_supported)
        except Exception:
            pass
        try:
            self._history_view_sticky = seed.history_view_sticky  # type: ignore[assignment]
        except Exception:
            pass
        try:
            self._syntax_prepared = dict(seed.syntax_prepared)  # type: ignore[arg-type]
        except Exception:
            pass
        try:
            self._syntax_attempted = set(seed.syntax_attempted)
        except Exception:
            pass
        try:
            self._dangling_refs = dict(seed.dangling_refs)  # type: ignore[arg-type]
        except Exception:
            pass
        self._split_anchor = seed.reading_anchor
        self._body = None
        self._body_width = None
        self._label_layer = None

    def _build_label_layer(self, width: int, hint_offset: int = 0) -> PagerLabelLayer:
        if self._labels_suppressed():
            self._label_window_scope = None
            # Band hints go too; keeping the band targets (minus their
            # letters) stops the band from re-requesting a recompose.
            self._time_band_hints = {}
            self._time_band_labels = self._time_band_targets()
            return PagerLabelLayer(
                labels=(),
                hint_to_label_index={},
                labels_by_section=tuple(() for _section in self.document.sections),
                target_count=0,
                mode="document",
            )
        return super()._build_label_layer(width, hint_offset=hint_offset)  # type: ignore[misc]

    def _labels_suppressed(self) -> bool:
        """Return whether this pane is an unfocused split pane (no badges)."""
        return bool(getattr(self, "_pane_framed", False)) and not getattr(
            self, "_pane_focused", True
        )

    def on_click(self, event: object) -> None:
        """Focus this pane when clicked in a split."""
        try:
            host = self.pager_host
            focus = getattr(host, "focus_view", None)
            if callable(focus):
                focus(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def on_mouse_down(self, event: object) -> None:
        """Focus this pane on any mouse press, like a click."""
        self.on_click(event)

    def on_descendant_focus(self, event: object) -> None:
        """Sync logical focus when Textual focus lands inside this pane."""
        try:
            host = self.pager_host
            focus = getattr(host, "focus_view", None)
            if callable(focus):
                focus(self)  # type: ignore[arg-type]
        except Exception:
            pass

    def on_unmount(self) -> None:
        try:
            self.app.theme_changed_signal.unsubscribe(self)
        except Exception:
            pass
        cancel_pump_free_tasks(self)

    def compose(self) -> ComposeResult:
        yield Static(id="pager-subject")
        yield Static(id="pager-trail", classes="hidden")
        yield Static(id="pager-time", classes="hidden")
        yield Static(id="pager-chrome-rule")
        with PagerBodyScroll(id="pager-body-scroll"):
            yield PagerBody(id="pager-body")
        yield Static(id="pager-search-command", classes="hidden")
        yield Static(id="pager-goto-command", classes="hidden")

    def on_mount(self) -> None:
        with tui_trace("pager.open", sections=len(self.document.sections)):
            self.query_one("#pager-chrome-rule", Static).update(Rule(style="dim"))
            self._ensure_body()
            self._update_trail()
            self._update_footer()
            self._update_subject()
            try:
                self.app.theme_changed_signal.subscribe(
                    self, self._on_app_theme_changed
                )
            except Exception:
                # Hosts without a theme signal (unit-test hosts) keep the
                # legacy watcher; it behaves identically while mounted.
                self.watch(self.app, "theme", self._on_app_theme_changed, init=False)
            anchor = self._split_anchor
            self._split_anchor = None
            if anchor is not None:
                composed = self._body
                document = self.document

                def _scroll_to_seed() -> None:
                    try:
                        if not self.is_mounted:
                            return
                        if self.document is not document:
                            return
                        body = self._body
                        if body is None or body is not composed:
                            return
                        target = row_for_reading_anchor(body, anchor)
                        scroll = self._body_scroll()
                        clamped = max(0, min(target, int(scroll.max_scroll_y)))
                        scroll.scroll_to(y=clamped, animate=False, immediate=True)
                        self._update_chrome_position()
                    except Exception:
                        pass

                try:
                    self.call_after_refresh(_scroll_to_seed)
                except Exception:
                    pass
            self._start_syntax_preparation_after_paint()
            self._start_history_discovery_after_paint()


__all__ = ["PagerView", "PagerViewSeed"]
