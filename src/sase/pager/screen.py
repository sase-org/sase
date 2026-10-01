"""``PagerScreen``: the thin host around one (later two) ``PagerView``s.

All per-document state, chrome rows, lifecycle and key handling live on
``PagerView``. This screen composes the shared footer, owns focus
routing, and dismisses the modal. Attribute reads and per-document
writes that existing callers address at the screen (``screen.document``,
``screen._back_trail``, ``screen._apply_resolution(...)``) forward to
the focused view, so single-pane behavior is unchanged.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from rich.rule import Rule
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.graphics import view_artifact_files
from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from sase.pager._help import PagerHelpScreen
from sase.pager._screen_actions import PagerActionMixin
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
from sase.pager._styles import PAGER_CSS
from sase.pager.app import AttachedTargetHandler, PagerExit, ResolveRef
from sase.pager.document import PagerDocument
from sase.pager.resolve import resolve_link as resolve_ref
from sase.pager.split import (
    PagerSplitLayout,
    PagerSplitState,
    close_focused_pane,
    initial_split_state,
    split_fits,
    step_ratio,
    toggle_focus,
    toggle_split,
)
from sase.pager.view import PagerView, PagerViewSeed

_MIXIN_STACK = (
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
)

#: Method names the view-owning mixins define. Reads of these on the
#: screen (binding dispatch, tests) resolve to the focused view.
#: ``dir`` (not ``vars``) so facades that compose split mixins via
#: inheritance still forward inherited methods.
_VIEW_METHOD_ATTRS = frozenset(
    name
    for mixin in _MIXIN_STACK
    for name in dir(mixin)
    if not (name.startswith("__") and name.endswith("__"))
)

#: Per-document instance state that lives on the view. Writes to these
#: on the screen forward to the focused view.
_VIEW_STATE_ATTRS = frozenset(
    {
        "links_enabled",
        "syntax_enabled",
        "_attached_handlers",
        "_resolve_ref",
        "_refresh_document_fn",
        "_refresh_in_flight",
        "_body",
        "_body_width",
        "_label_layer",
        "_label_pending_prefix",
        "_label_window_scope",
        "_last_activated_label",
        "_pending_action",
        "_dangling_refs",
        "_resolve_generation",
        "_search",
        "_back_trail",
        "_forward_trail",
        "_trail_render_signature",
        "_footer_status",
        "_goto_active",
        "_goto_digits",
        "_goto_mark",
        "_syntax_palette",
        "_syntax_generation",
        "_syntax_prepared",
        "_syntax_attempted",
        "_syntax_result_cache",
        "_syntax_styled_cache",
        "_syntax_restart_requested",
        "_syntax_pass_running",
        "_syntax_document_span_budget_used",
        "_history_states",
        "_history_generation",
        "_history_pending",
        "_history_supported",
        "_history_indexing",
        "_history_coalesced",
        "_history_view_sticky",
        "_history_miss_notice",
        "_time_band_labels",
        "_time_band_hints",
        "_time_band_signature",
        "_time_band_now_epoch",
        "_last_composed_width",
        "_body_generation",
        "_pane_framed",
        "_pane_focused",
        "_split_anchor",
        "_chrome_signature",
    }
)

_VIEW_ATTRS = _VIEW_METHOD_ATTRS | _VIEW_STATE_ATTRS

#: Writes to these screen attributes land on the focused view. ``notify``
#: is here because tests patch ``screen.notify`` to capture toasts, while
#: the toast call sites now run on the view.
_VIEW_FORWARD_WRITES = _VIEW_ATTRS | {"notify"}


class PagerScreen(ModalScreen[PagerExit]):
    """Host one focused ``PagerView`` plus the shared footer.

    The constructor signature is unchanged; per-document actions bound
    here dispatch to same-named ``action_*`` methods on the focused
    view.
    """

    CSS = PAGER_CSS

    BINDINGS = [
        Binding("left_parenthesis", "history_older", "Older", show=False),
        Binding("right_parenthesis", "history_newer", "Newer", show=False),
        Binding("left_curly_bracket", "history_first", "First", show=False),
        Binding("right_curly_bracket", "history_now", "Now", show=False),
        Binding("equals_sign", "history_toggle_diff", "Diff", show=False),
        Binding("at", "history_timeline", "Timeline", show=False),
        Binding(
            "left_square_bracket", "history_prev_change", "Prev change", show=False
        ),
        Binding(
            "right_square_bracket", "history_next_change", "Next change", show=False
        ),
        Binding("q,escape", "close_pager", "Close"),
        Binding("j,down", "scroll_down", "Down"),
        Binding("k,up", "scroll_up", "Up"),
        Binding("ctrl+d", "scroll_half_down", "Half Down"),
        Binding("ctrl+u", "scroll_half_up", "Half Up"),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
        Binding("semicolon,colon", "goto_line", "Go to Line"),
        Binding("ctrl+n", "next_section", "Next Section"),
        Binding("ctrl+p", "prev_section", "Prev Section"),
        Binding("backspace,ctrl+o", "trail_back", "Back"),
        Binding("tab,ctrl+i", "trail_forward", "Forward", key_display="<ctrl+i>"),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "arm_copy", "Copy"),
        Binding("E", "arm_edit", "Edit"),
        Binding("question_mark", "show_help", "Keys"),
        Binding("backslash", "split_below", "Split below", show=False),
        Binding("vertical_line", "split_beside", "Split beside", show=False),
        Binding("ctrl+f", "focus_other", "Focus other pane", show=False),
        Binding("plus", "grow_pane", "Grow pane", show=False),
        Binding("minus", "shrink_pane", "Shrink pane", show=False),
    ]

    def __init__(
        self,
        document: PagerDocument,
        *,
        links_enabled: bool = True,
        attached_handlers: Mapping[str, AttachedTargetHandler] | None = None,
        resolve_ref_fn: ResolveRef | None = None,
        syntax_enabled: bool = True,
        refresh_document_fn: Callable[[], PagerDocument | None] | None = None,
    ) -> None:
        """Host one `PagerDocument` (see ``PagerView`` for the semantics).

        ``refresh_document_fn``, when given, is invoked from a worker thread
        by ``r`` to re-snapshot a live source (e.g. a running agent) instead
        of merely recomposing the frozen document; it must be thread-safe. A
        ``None`` return or a raised exception keeps the current document.
        """
        super().__init__()
        # Evaluate the module-global resolver now so a test that patches
        # ``sase.pager.screen.resolve_ref`` before construction still wins.
        resolve = resolve_ref if resolve_ref_fn is None else resolve_ref_fn
        handlers: Mapping[str, AttachedTargetHandler] = (
            {} if attached_handlers is None else attached_handlers
        )
        self._focused_index = 0
        self._split_state: PagerSplitState = initial_split_state()
        self._split_in_flight = False
        self._views: list[PagerView] = [
            PagerView(
                document,
                links_enabled=links_enabled,
                attached_handlers=handlers,
                resolve_ref=resolve,
                syntax_enabled=syntax_enabled,
                refresh_document_fn=refresh_document_fn,
            )
        ]

    @property
    def views(self) -> tuple[PagerView, ...]:
        """The hosted views in layout order."""
        return tuple(self._views)

    @property
    def focused_view(self) -> PagerView:
        """The view that receives keys and owns the footer."""
        return self._views[self._focused_index]

    @property
    def document(self) -> PagerDocument:
        """The focused view's document."""
        return self.focused_view.document

    def _focused_for_forward(self) -> Any:
        try:
            views = object.__getattribute__(self, "_views")
        except AttributeError:
            return None
        if not views:
            return None
        try:
            index = int(object.__getattribute__(self, "_focused_index"))
        except Exception:
            index = 0
        if 0 <= index < len(views):
            return views[index]
        return views[0]

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in {"_views", "_focused_index", "_split_state", "_split_in_flight"}:
            raise AttributeError(name)
        view = self._focused_for_forward()
        if view is None:
            raise AttributeError(name) from None
        return getattr(view, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _VIEW_FORWARD_WRITES:
            view = self._focused_for_forward()
            if view is None:
                object.__setattr__(self, name, value)
                return
            setattr(view, name, value)
            return
        object.__setattr__(self, name, value)

    def paint_footer(self, view: PagerView, legend: Any) -> None:
        """Paint the shared footer when *view* is the focused one."""
        try:
            if view is not self.focused_view:
                return
        except Exception:
            return
        try:
            self.query_one("#pager-footer", Static).update(legend)
        except Exception:
            pass

    def focus_view(self, view: PagerView) -> None:
        """Move logical focus to *view* (a no-op when already focused)."""
        try:
            index = self._views.index(view)
        except ValueError:
            return
        if index == self._focused_index:
            return
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        self._focused_index = index
        self._split_state = PagerSplitState(
            layout=self._split_state.layout,
            focused=index,
            ratio=self._split_state.ratio,
        )
        self._apply_split_state()

    def close_view(self, view: PagerView, *, trail_exhausted: bool = False) -> None:
        """Close *view*; with one view this dismisses the pager."""
        try:
            is_split = self._split_state.layout is not PagerSplitLayout.SINGLE
        except Exception:
            is_split = len(getattr(self, "_views", ())) > 1
        if not is_split:
            self.dismiss(PagerExit(trail_exhausted=trail_exhausted))
            return
        try:
            index = self._views.index(view)
        except ValueError:
            return
        if self._split_in_flight:
            return
        self._split_in_flight = True

        async def _remove() -> None:
            try:
                other_index = 1 - index if len(self._views) == 2 else 0
                survivor = self._views[other_index]
                await self.query_one("#pager-panes", Vertical).remove_children()
                self._views = [survivor]
                self._focused_index = 0
                self._split_state = close_focused_pane(self._split_state)
                # The survivor fills the screen: clear its frame.
                try:
                    survivor.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
                self._apply_split_state()
            finally:
                self._split_in_flight = False

        self.run_worker(_remove(), exclusive=True)

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    def compose(self) -> ComposeResult:
        with Vertical(id="pager-root"):
            with Vertical(id="pager-panes"):
                yield from self._views
            yield Static(id="pager-footer-rule")
            yield Static(id="pager-footer")

    def on_mount(self) -> None:
        self.query_one("#pager-footer-rule", Static).update(Rule(style="dim"))
        self._apply_split_state()

    @property
    def is_split(self) -> bool:
        """Return whether two panes are currently shown."""
        try:
            return self._split_state.layout is not PagerSplitLayout.SINGLE
        except Exception:
            return len(getattr(self, "_views", ())) > 1

    def _panes_size(self) -> tuple[int, int]:
        """Return the ``#pager-panes`` width and height for fit checks."""
        try:
            panes = self.query_one("#pager-panes", Vertical)
            return (max(int(panes.size.width), 0), max(int(panes.size.height), 0))
        except Exception:
            pass
        try:
            return (max(int(self.size.width), 0), max(int(self.size.height), 0))
        except Exception:
            return (0, 0)

    def _refuse_split_toast(
        self, target: PagerSplitLayout, width: int, height: int
    ) -> None:
        """Toast why *target* cannot open, suggesting what would fit."""
        other = (
            PagerSplitLayout.BESIDE
            if target is PagerSplitLayout.BELOW
            else PagerSplitLayout.BELOW
        )
        if split_fits(other, 50, width, height):
            hint = (
                "try | for side by side"
                if target is PagerSplitLayout.BELOW
                else "try \\ for below"
            )
            where = "below" if target is PagerSplitLayout.BELOW else "side by side"
            self.notify(
                f"Not enough room to split {where} — {hint}.",
                severity="information",
            )
            return
        self.notify("Window too small to split.", severity="information")

    async def _toggle_split(self, target: PagerSplitLayout) -> None:
        """Open, rotate, or unsplit for *target* behind the in-flight guard."""
        if self._split_in_flight:
            return
        current = self._split_state
        if current.layout is PagerSplitLayout.SINGLE:
            width, height = self._panes_size()
            if not split_fits(target, 50, width, height):
                self._refuse_split_toast(target, width, height)
                return
            self._split_in_flight = True
            try:
                source = self.focused_view
                seed: PagerViewSeed = source.split_seed()
                try:
                    first = self.query_one("#pager-panes", Vertical)
                except Exception:
                    self._split_in_flight = False
                    return
                new_view = PagerView(
                    seed.document,
                    links_enabled=source.links_enabled,
                    attached_handlers=source._attached_handlers,
                    resolve_ref=source._resolve_ref,
                    syntax_enabled=source.syntax_enabled,
                    refresh_document_fn=source._refresh_document_fn,
                )
                new_view.apply_split_seed(seed)
                await first.mount(new_view)
                self._views = [source, new_view]
                self._focused_index = 1
                self._split_state = toggle_split(current, target)
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        if current.layout is target:
            # Same key keeps the focused pane (vim's ctrl-w o).
            if self._split_in_flight:
                return
            self._split_in_flight = True
            try:
                survivor = self.focused_view
                await self.query_one("#pager-panes", Vertical).remove_children()
                self._views = [survivor]
                self._focused_index = 0
                self._split_state = toggle_split(current, target)
                try:
                    survivor.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
                self._apply_split_state()
            finally:
                self._split_in_flight = False
            return
        width, height = self._panes_size()
        if not split_fits(target, current.ratio, width, height) and not split_fits(
            target, 50, width, height
        ):
            self._refuse_split_toast(target, width, height)
            return
        self._split_state = toggle_split(current, target)
        self._apply_split_state()

    def _apply_split_state(self) -> None:
        """Push the pure split state into container, panes, and footer."""
        try:
            state = self._split_state
        except Exception:
            return
        try:
            panes = self.query_one("#pager-panes", Vertical)
        except Exception:
            return
        single = state.layout is PagerSplitLayout.SINGLE
        try:
            panes.remove_class("-single", "-below", "-beside")
            if single:
                panes.add_class("-single")
            elif state.layout is PagerSplitLayout.BELOW:
                panes.add_class("-below")
            else:
                panes.add_class("-beside")
        except Exception:
            pass
        try:
            views = list(self._views)
            if len(views) == 2 and not single:
                first, second = views
                ratio = int(state.ratio)
                if state.layout is PagerSplitLayout.BELOW:
                    first.styles.height = f"{ratio}fr"
                    second.styles.height = f"{100 - ratio}fr"
                    first.styles.width = "1fr"
                    second.styles.width = "1fr"
                else:
                    first.styles.width = f"{ratio}fr"
                    second.styles.width = f"{100 - ratio}fr"
                    first.styles.height = "1fr"
                    second.styles.height = "1fr"
                first.set_pane_role(framed=True, focused=(state.focused == 0))
                second.set_pane_role(framed=True, focused=(state.focused == 1))
            elif views:
                only = views[0] if len(views) == 1 else views[state.focused]
                try:
                    only.styles.height = "1fr"
                    only.styles.width = "1fr"
                except Exception:
                    pass
                try:
                    only.set_pane_role(framed=False, focused=True)
                except Exception:
                    pass
                self._focused_index = 0
        except Exception:
            pass
        try:
            rule = self.query_one("#pager-footer-rule", Static)
            if single:
                rule.remove_class("hidden")
            else:
                rule.add_class("hidden")
        except Exception:
            pass
        try:
            focused = self.focused_view
        except Exception:
            return
        try:
            focused._update_footer()
        except Exception:
            pass
        try:
            scroll = focused.query_one("#pager-body-scroll", Static)
            self.call_after_refresh(scroll.focus)  # type: ignore[attr-defined]
        except Exception:
            pass

    def on_key(self, event: Key) -> None:
        """Give the re-hosted vim search first refusal on every keypress.

        ``allow_question_mark_reverse=False`` reserves ``?`` for the wider
        help binding once committed search exits, per the controller's own
        documented escape hatch for hosts with a house ``?`` binding.
        ``passthrough_exit_keys=None`` exits committed search on any other
        key rather than Zoom's narrower structural set, because this app has
        only one scroll target - there is no second panel for a raw ``j``
        to land on while search is still showing.

        Skipped entirely while a modal (such as the help screen) is on top,
        so a search cannot silently start underneath it.
        """
        if self.app.screen is not self:
            return
        view = self.focused_view
        if view.handle_goto_key(event):
            event.prevent_default()
            event.stop()
            return
        if event.key == "question_mark" and view._search.mode != "typing":
            self.action_show_help()
            event.prevent_default()
            event.stop()
            return
        disposition = view._search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=None,
            allow_question_mark_reverse=False,
        )
        if disposition == "consumed":
            event.prevent_default()
            event.stop()
            return
        # Split keys win over an armed label prefix so `\` / `|` / ctrl+f /
        # `+` / `-` always reach their bindings instead of being swallowed
        # as "no link label matches".
        if event.key in ("backslash", "vertical_line", "ctrl+f", "plus", "minus"):
            return

        if view._handle_label_key(event):
            event.prevent_default()
            event.stop()

    def _view_action(self, name: str) -> None:
        getattr(self.focused_view, f"action_{name}")()

    def action_history_older(self) -> None:
        self._view_action("history_older")

    def action_history_newer(self) -> None:
        self._view_action("history_newer")

    def action_history_first(self) -> None:
        self._view_action("history_first")

    def action_history_now(self) -> None:
        self._view_action("history_now")

    def action_history_toggle_diff(self) -> None:
        self._view_action("history_toggle_diff")

    def action_history_timeline(self) -> None:
        self._view_action("history_timeline")

    def action_history_prev_change(self) -> None:
        self._view_action("history_prev_change")

    def action_history_next_change(self) -> None:
        self._view_action("history_next_change")

    def action_scroll_down(self) -> None:
        self._view_action("scroll_down")

    def action_scroll_up(self) -> None:
        self._view_action("scroll_up")

    def action_scroll_half_down(self) -> None:
        self._view_action("scroll_half_down")

    def action_scroll_half_up(self) -> None:
        self._view_action("scroll_half_up")

    def action_scroll_top(self) -> None:
        self._view_action("scroll_top")

    def action_scroll_bottom(self) -> None:
        self._view_action("scroll_bottom")

    def action_goto_line(self) -> None:
        self._view_action("goto_line")

    def action_next_section(self) -> None:
        self._view_action("next_section")

    def action_prev_section(self) -> None:
        self._view_action("prev_section")

    def action_trail_back(self) -> None:
        self._view_action("trail_back")

    def action_trail_forward(self) -> None:
        self._view_action("trail_forward")

    def action_refresh(self) -> None:
        self._view_action("refresh")

    def action_arm_copy(self) -> None:
        self._view_action("arm_copy")

    def action_arm_edit(self) -> None:
        self._view_action("arm_edit")

    def action_close_pager(self) -> None:
        self.close_view(self.focused_view)

    async def action_split_below(self) -> None:
        await self._toggle_split(PagerSplitLayout.BELOW)

    async def action_split_beside(self) -> None:
        await self._toggle_split(PagerSplitLayout.BESIDE)

    def action_focus_other(self) -> None:
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        self._focused_index = 1 - self._focused_index
        self._split_state = toggle_focus(self._split_state)
        self._apply_split_state()

    def action_grow_pane(self) -> None:
        self._step_pane_ratio(+1)

    def action_shrink_pane(self) -> None:
        self._step_pane_ratio(-1)

    def _step_pane_ratio(self, direction: int) -> None:
        """Grow/shrink the focused pane one step, clamping silently."""
        if self._split_state.layout is PagerSplitLayout.SINGLE:
            return
        candidate = step_ratio(self._split_state, direction)
        if candidate == self._split_state:
            return
        width, height = self._panes_size()
        if not split_fits(candidate.layout, candidate.ratio, width, height):
            return
        self._split_state = candidate
        self._apply_split_state()

    def action_show_help(self) -> None:
        view = self.focused_view
        self.app.push_screen(
            PagerHelpScreen(
                section_total=len(view.document.sections),
                label_count=view._visible_label_count(),
                trail_snapshot=view._trail_snapshot(),
            )
        )


__all__ = [
    "PagerScreen",
    "resolve_ref",
    "subprocess",
    "suspend_for_external_tool",
    "view_artifact_files",
]
