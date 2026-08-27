"""``PagerScreen``: the reusable Textual reading surface."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping

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
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets.vim_search_controller import VimSearchController
from sase.pager._help import PagerHelpScreen
from sase.pager._labels import LabelWindowScope, PagerLabel, PagerLabelLayer
from sase.pager._layout import ComposedBody
from sase.pager._screen_actions import PagerActionMixin
from sase.pager._screen_body import PagerBodyMixin
from sase.pager._screen_chrome import PagerChromeMixin
from sase.pager._screen_search import PagerSearchMixin
from sase.pager._screen_trail import PagerTrailMixin
from sase.pager._screen_widgets import PagerBody, PagerBodyScroll
from sase.pager._styles import PAGER_CSS
from sase.pager.app import AttachedTargetHandler, PagerExit, PendingAction, ResolveRef
from sase.pager.document import PagerDocument
from sase.pager.resolve import resolve_ref
from sase.pager.trail import PagerTrailEntry


class PagerScreen(
    PagerBodyMixin,
    PagerActionMixin,
    PagerTrailMixin,
    PagerChromeMixin,
    PagerSearchMixin,
    ModalScreen[PagerExit],
):
    """A link-traversing document reader: chrome, scrollable body, footer.

    This phase paints no jump-hint keys yet (that is the ``labels`` phase) -
    it only owns the sticky chrome, the virtualized scrollable body, section
    rules, ``ctrl+n``/``ctrl+p`` scroll-to-header, the availability-driven
    footer, and a re-hosted vim search.
    """

    CSS = PAGER_CSS

    BINDINGS = [
        Binding("q,escape", "close_pager", "Close"),
        Binding("j,down", "scroll_down", "Down"),
        Binding("k,up", "scroll_up", "Up"),
        Binding("ctrl+d", "scroll_half_down", "Half Down"),
        Binding("ctrl+u", "scroll_half_up", "Half Up"),
        Binding("g", "scroll_top", "Top"),
        Binding("G", "scroll_bottom", "Bottom"),
        Binding("ctrl+n", "next_section", "Next Section"),
        Binding("ctrl+p", "prev_section", "Prev Section"),
        Binding("backspace,ctrl+o", "trail_back", "Back"),
        Binding("ctrl+i", "trail_forward", "Forward"),
        Binding("r", "refresh", "Refresh"),
        Binding("y", "arm_copy", "Copy"),
        Binding("E", "arm_edit", "Edit"),
        Binding("question_mark", "show_help", "Keys"),
    ]

    def __init__(
        self,
        document: PagerDocument,
        *,
        links_enabled: bool = True,
        attached_handlers: Mapping[str, AttachedTargetHandler] | None = None,
        resolve_ref_fn: ResolveRef | None = None,
    ) -> None:
        super().__init__()
        self.document = document
        self.links_enabled = links_enabled
        self._attached_handlers: Mapping[str, AttachedTargetHandler] = (
            {} if attached_handlers is None else attached_handlers
        )
        self._resolve_ref = resolve_ref if resolve_ref_fn is None else resolve_ref_fn
        self._body: ComposedBody | None = None
        self._body_width: int | None = None
        self._label_layer: PagerLabelLayer | None = None
        self._label_pending_prefix = ""
        self._label_window_scope: LabelWindowScope | None = None
        self._last_activated_label: PagerLabel | None = None
        self._pending_action: PendingAction = "follow"
        self._dangling_refs: set[str] = set()
        self._resolve_generation = 0
        self._search = VimSearchController(self)
        self._back_trail: list[PagerTrailEntry] = []
        self._forward_trail: list[PagerTrailEntry] = []
        self._footer_status: str | None = None

    def on_unmount(self) -> None:
        cancel_pump_free_tasks(self)

    def compose(self) -> ComposeResult:
        with Vertical(id="pager-root"):
            yield Static(id="pager-subject")
            yield Static(id="pager-trail", classes="hidden")
            yield Static(id="pager-chrome-rule")
            with PagerBodyScroll(id="pager-body-scroll"):
                yield PagerBody(id="pager-body")
            yield Static(id="pager-search-command", classes="hidden")
            yield Static(id="pager-footer-rule")
            yield Static(id="pager-footer")

    def on_mount(self) -> None:
        with tui_trace("pager.open", sections=len(self.document.sections)):
            self.query_one("#pager-chrome-rule", Static).update(Rule(style="dim"))
            self.query_one("#pager-footer-rule", Static).update(Rule(style="dim"))
            self._ensure_body()
            self._update_trail()
            self._update_footer()
            self._update_subject()

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
        disposition = self._search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=None,
            allow_question_mark_reverse=False,
        )
        if disposition == "consumed":
            event.prevent_default()
            event.stop()
            return

        if self._handle_label_key(event):
            event.prevent_default()
            event.stop()

    def action_close_pager(self) -> None:
        self.dismiss(PagerExit())

    def action_show_help(self) -> None:
        self.app.push_screen(
            PagerHelpScreen(
                section_total=len(self.document.sections),
                label_count=self._visible_label_count(),
                trail_entries=self._trail_strip_entries(),
            )
        )


__all__ = [
    "PagerScreen",
    "resolve_ref",
    "subprocess",
    "suspend_for_external_tool",
    "view_artifact_files",
]
