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
from typing import Protocol

from rich.rule import Rule
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import Static

from sase.ace.tui.util.pump_tasks import cancel_pump_free_tasks
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets.vim_search_controller import VimSearchController
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager._screen_actions import PagerActionMixin, _DanglingRefKey
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
from sase.pager.app import AttachedTargetHandler, PendingAction, ResolveRef
from sase.pager.document import PagerDocument
from sase.pager.trail import PagerTrailEntry


class PagerViewHost(Protocol):
    """What a ``PagerView`` needs from its hosting screen.

    Views never import ``PagerScreen``; the screen satisfies this
    protocol structurally. Later split phases extend it with focus
    requests and other-pane display.
    """

    def paint_footer(self, view: PagerView, legend: object) -> None:
        """Paint *legend* into the shared footer when *view* is focused."""
        ...

    def close_view(self, view: PagerView, *, trail_exhausted: bool = False) -> None:
        """Close *view*; dismiss the pager when the last view closes."""
        ...


class PagerView(
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
        self._pending_action: PendingAction = "follow"
        self._dangling_refs: dict[_DanglingRefKey, str] = {}
        self._resolve_generation = 0
        self._search = VimSearchController(self)
        self._back_trail: list[PagerTrailEntry] = []
        self._forward_trail: list[PagerTrailEntry] = []
        self._trail_render_signature: object | None = None
        self._footer_status: str | None = None
        self._init_goto_state()
        self._init_syntax_state()
        self._init_history_state()
        self._init_diff_state()
        self._init_time_band_state()

    @property
    def pager_host(self) -> PagerViewHost:
        """Return the hosting screen cast to the view-host protocol."""
        return self.screen  # type: ignore[return-value]

    def _chrome_height(self) -> int:
        """Height the trail/time chrome budgets degrade against.

        Single-pane rendering historically measured the whole screen
        (footer rows included); keep measuring it so budgets stay
        byte-identical until framed split panes compact per-pane chrome
        deliberately.
        """
        try:
            return max(int(self.screen.size.height), 1)
        except Exception:
            return max(int(self.size.height), 1)

    def on_unmount(self) -> None:
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
            self.watch(self.app, "theme", self._on_app_theme_changed, init=False)
            self._start_syntax_preparation_after_paint()
            self._start_history_discovery_after_paint()

    def handle_view_key(self, event: Key) -> bool:
        """Consume goto-prompt, search, and label keys for this view.

        Mirrors the old screen precedence: the goto prompt first, then the
        re-hosted vim search, then label keys. The host's ``?`` help sits
        between search and labels, so the screen expands this sequence
        instead of calling it directly.
        """
        if self.handle_goto_key(event):
            return True
        disposition = self._search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=None,
            allow_question_mark_reverse=False,
        )
        if disposition == "consumed":
            return True
        return self._handle_label_key(event)


__all__ = ["PagerView", "PagerViewHost"]
