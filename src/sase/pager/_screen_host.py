"""Host chrome and view forwarding for ``PagerScreen``.

Owns construction of the initial :class:`PagerView`, focused-view
forwarding (``__getattr__`` / ``__setattr__``), footer painting,
composition, mount lifecycle, key routing, and the thin ``action_*``
delegations that forward to the focused view. ``BINDINGS``/``CSS`` live
on the ``PagerScreen`` facade itself (Textual only merges those from
``DOMNode`` bases). Split-pane state and layout live in
:mod:`sase.pager._screen_split`; this module never imports that sibling.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from rich.rule import Rule
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import Static

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
from sase.pager.app import AttachedTargetHandler, ResolveRef
from sase.pager.document import PagerDocument
from sase.pager.split import PagerSplitState, initial_split_state
from sase.pager.view import PagerView

__all__ = ["PagerScreenHostMixin"]

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


def _facade_resolve_ref() -> ResolveRef:
    """Return the current ``sase.pager.screen.resolve_ref`` facade value."""
    import sys

    mod = sys.modules.get("sase.pager.screen")
    candidate = getattr(mod, "resolve_ref", None) if mod is not None else None
    if callable(candidate):
        return candidate
    from sase.pager.resolve import resolve_link as fallback

    return fallback


class PagerScreenHostMixin:
    """Host one focused ``PagerView`` plus the shared footer."""

    def __init__(
        self: Any,
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
        # Evaluate the facade module-global resolver now so a test that patches
        # ``sase.pager.screen.resolve_ref`` before construction still wins.
        resolve = _facade_resolve_ref() if resolve_ref_fn is None else resolve_ref_fn
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
    def views(self: Any) -> tuple[PagerView, ...]:
        """The hosted views in layout order."""
        return tuple(self._views)

    @property
    def focused_view(self: Any) -> PagerView:
        """The view that receives keys and owns the footer."""
        return self._views[self._focused_index]

    @property
    def document(self: Any) -> PagerDocument:
        """The focused view's document."""
        return self.focused_view.document

    def _focused_for_forward(self: Any) -> Any:
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

    def __getattr__(self: Any, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        if name in {"_views", "_focused_index", "_split_state", "_split_in_flight"}:
            raise AttributeError(name)
        view = self._focused_for_forward()
        if view is None:
            raise AttributeError(name) from None
        return getattr(view, name)

    def __setattr__(self: Any, name: str, value: Any) -> None:
        if name in _VIEW_FORWARD_WRITES:
            view = self._focused_for_forward()
            if view is None:
                object.__setattr__(self, name, value)
                return
            setattr(view, name, value)
            return
        object.__setattr__(self, name, value)

    def paint_footer(self: Any, view: PagerView, legend: Any) -> None:
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

    def on_unmount(self: Any) -> None:
        cancel_pump_free_tasks(self)

    def compose(self: Any) -> ComposeResult:
        with Vertical(id="pager-root"):
            with Vertical(id="pager-panes"):
                yield from self._views
            yield Static(id="pager-footer-rule")
            yield Static(id="pager-footer")

    def on_mount(self: Any) -> None:
        self.query_one("#pager-footer-rule", Static).update(Rule(style="dim"))
        self._apply_split_state()

    def on_key(self: Any, event: Key) -> None:
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

    def _view_action(self: Any, name: str) -> None:
        getattr(self.focused_view, f"action_{name}")()

    def action_history_older(self: Any) -> None:
        self._view_action("history_older")

    def action_history_newer(self: Any) -> None:
        self._view_action("history_newer")

    def action_history_first(self: Any) -> None:
        self._view_action("history_first")

    def action_history_now(self: Any) -> None:
        self._view_action("history_now")

    def action_history_toggle_diff(self: Any) -> None:
        self._view_action("history_toggle_diff")

    def action_history_timeline(self: Any) -> None:
        self._view_action("history_timeline")

    def action_history_prev_change(self: Any) -> None:
        self._view_action("history_prev_change")

    def action_history_next_change(self: Any) -> None:
        self._view_action("history_next_change")

    def action_scroll_down(self: Any) -> None:
        self._view_action("scroll_down")

    def action_scroll_up(self: Any) -> None:
        self._view_action("scroll_up")

    def action_scroll_half_down(self: Any) -> None:
        self._view_action("scroll_half_down")

    def action_scroll_half_up(self: Any) -> None:
        self._view_action("scroll_half_up")

    def action_scroll_top(self: Any) -> None:
        self._view_action("scroll_top")

    def action_scroll_bottom(self: Any) -> None:
        self._view_action("scroll_bottom")

    def action_goto_line(self: Any) -> None:
        self._view_action("goto_line")

    def action_next_section(self: Any) -> None:
        self._view_action("next_section")

    def action_prev_section(self: Any) -> None:
        self._view_action("prev_section")

    def action_trail_back(self: Any) -> None:
        self._view_action("trail_back")

    def action_trail_forward(self: Any) -> None:
        self._view_action("trail_forward")

    def action_refresh(self: Any) -> None:
        self._view_action("refresh")

    def action_arm_copy(self: Any) -> None:
        self._view_action("arm_copy")

    def action_arm_edit(self: Any) -> None:
        self._view_action("arm_edit")

    def action_arm_other(self: Any) -> None:
        self._view_action("arm_other")

    def action_close_pager(self: Any) -> None:
        self.close_view(self.focused_view)

    def action_show_help(self: Any) -> None:
        view = self.focused_view
        self.app.push_screen(
            PagerHelpScreen(
                section_total=len(view.document.sections),
                label_count=view._visible_label_count(),
                trail_snapshot=view._trail_snapshot(),
            )
        )
