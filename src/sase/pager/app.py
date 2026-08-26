"""``SasePager``: the standalone Textual reading surface.

Not wired to any caller yet (design doc phase `viewer`). ``sase bead show``,
the Agents-tab ``v`` keymap, and the future ``sase pager`` command all run
this same app in-process — the CLI calls ``.run()``, ACE runs it inside
``with self.suspend():`` — the way ``MemoryReviewTuiApp`` already proves both
halves of this exact pattern in this tree (design doc section D1).
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.rule import Rule
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.events import Key, Resize
from textual.widgets import Static

from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
)
from sase.pager._chrome import footer_legend, subject_line
from sase.pager._help import PagerHelpScreen
from sase.pager._layout import (
    ComposedBody,
    compose_body,
    current_section_index,
    search_corpus,
)
from sase.pager._styles import PAGER_CSS
from sase.pager.document import PagerDocument


@dataclass(frozen=True, slots=True)
class PagerExit:
    """The result of a finished ``SasePager`` run.

    Empty today; the ``trail`` phase (sase-uk.6) extends this with a
    trail-exhausted marker so a host resuming its own history can tell an
    ordinary quit from a fully-walked-back trail.
    """


class _PagerBodyScroll(VerticalScroll):
    """The body scroll container; its own width drives layout caching."""

    def on_resize(self, _event: Resize) -> None:
        app = self.app
        if isinstance(app, SasePager):
            app._ensure_body()
            app._update_subject()


class SasePager(App[PagerExit]):
    """A link-traversing document reader: chrome, scrollable body, footer.

    This phase paints no jump-hint keys yet (that is the ``labels`` phase) —
    it only owns the sticky chrome, the virtualized scrollable body, section
    rules, ``ctrl+n``/``ctrl+p`` scroll-to-header, the availability-driven
    footer, and a re-hosted vim search.
    """

    ENABLE_COMMAND_PALETTE = False
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
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "show_help", "Keys"),
    ]

    def __init__(self, document: PagerDocument) -> None:
        super().__init__()
        self.document = document
        self._body: ComposedBody | None = None
        self._body_width: int | None = None
        self._search = VimSearchController(self)

    def compose(self) -> ComposeResult:
        with Vertical(id="pager-root"):
            yield Static(id="pager-subject")
            yield Static(id="pager-trail", classes="hidden")
            yield Static(id="pager-chrome-rule")
            with _PagerBodyScroll(id="pager-body-scroll"):
                yield Static(id="pager-body")
            yield Static(id="pager-search-command", classes="hidden")
            yield Static(id="pager-footer-rule")
            yield Static(id="pager-footer")

    def on_mount(self) -> None:
        with tui_trace("pager.open", sections=len(self.document.sections)):
            self.query_one("#pager-chrome-rule", Static).update(Rule(style="dim"))
            self.query_one("#pager-footer-rule", Static).update(Rule(style="dim"))
            self.query_one("#pager-footer", Static).update(
                footer_legend(section_total=len(self.document.sections))
            )
            self._ensure_body()
            self._update_subject()

    def on_key(self, event: Key) -> None:
        """Give the re-hosted vim search first refusal on every keypress.

        ``allow_question_mark_reverse=False`` reserves ``?`` for the wider
        help binding once committed search exits, per the controller's own
        documented escape hatch for hosts with a house ``?`` binding.
        ``passthrough_exit_keys=None`` exits committed search on any other
        key rather than Zoom's narrower structural set, because this app has
        only one scroll target — there is no second panel for a raw ``j``
        to land on while search is still showing.

        Skipped entirely while a modal (such as the help screen) is on top,
        so a search cannot silently start underneath it.
        """
        if len(self.screen_stack) > 1:
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

    def action_close_pager(self) -> None:
        self.exit(PagerExit())

    def action_scroll_down(self) -> None:
        self._body_scroll().scroll_relative(y=1, animate=False)
        self._after_scroll()

    def action_scroll_up(self) -> None:
        self._body_scroll().scroll_relative(y=-1, animate=False)
        self._after_scroll()

    def action_scroll_half_down(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_half_up(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_relative(y=-max(1, scroll.size.height // 2), animate=False)
        self._after_scroll()

    def action_scroll_top(self) -> None:
        self._body_scroll().scroll_to(y=0, animate=False, immediate=True)
        self._after_scroll()

    def action_scroll_bottom(self) -> None:
        scroll = self._body_scroll()
        scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        self._after_scroll()

    def action_next_section(self) -> None:
        """Scroll so the next section's rule sits at row 0 (design doc D5).

        This is a scroll, not a screen swap — deliberately unlike
        ``ZoomPanelModal``'s ``ctrl+n``, because the pager is one continuous
        document rather than independently-loaded panels.
        """
        self._goto_section(1)

    def action_prev_section(self) -> None:
        self._goto_section(-1)

    def action_refresh(self) -> None:
        self._body_width = None
        self._ensure_body()
        self._after_scroll()

    def action_show_help(self) -> None:
        self.push_screen(PagerHelpScreen(section_total=len(self.document.sections)))

    def _goto_section(self, direction: int) -> None:
        if self._body is None or len(self.document.sections) <= 1:
            return
        scroll = self._body_scroll()
        offsets = self._body.section_offsets
        index = current_section_index(offsets, int(scroll.scroll_y))
        target = index + direction
        if target >= len(offsets):
            scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)
        else:
            target_row = offsets[max(target, 0)]
            scroll.scroll_to(y=target_row, animate=False, immediate=True)
        self._after_scroll()

    def _after_scroll(self) -> None:
        self.call_after_refresh(self._update_subject)

    def _body_scroll(self) -> _PagerBodyScroll:
        return self.query_one("#pager-body-scroll", _PagerBodyScroll)

    def _ensure_body(self) -> None:
        """Rebuild the composed body only when the body's width changed.

        Sections are frozen and already parsed once at document-construction
        time (``PagerSection.__post_init__``); this only recomputes the
        width-dependent layout — section row offsets and transition rules —
        per ``tui_perf`` rule 8.
        """
        scroll = self._body_scroll()
        width = max(scroll.size.width, 1)
        if self._body is not None and width == self._body_width:
            return
        self._body_width = width
        body = compose_body(self.document, width)
        self._body = body
        self.query_one("#pager-body", Static).update(body.renderable)

    def _update_subject(self) -> None:
        scroll = self._body_scroll()
        total = len(self.document.sections)
        width = max(scroll.size.width, 1)
        subject_widget = self.query_one("#pager-subject", Static)
        if total == 0:
            subject_widget.update(Text(self.document.title, style="bold"))
            return

        offsets = self._body.section_offsets if self._body is not None else (0,)
        index = current_section_index(offsets, int(scroll.scroll_y))
        section = self.document.sections[index]
        percent = (
            100
            if scroll.max_scroll_y <= 0
            else min(100, round(scroll.scroll_y / scroll.max_scroll_y * 100))
        )
        char_count = sum(len(part.plain_text) for part in self.document.sections)
        subject_widget.update(
            subject_line(
                self.document,
                section,
                section_index=index + 1,
                section_total=total,
                scroll_percent=percent,
                char_count=char_count,
                width=width,
            )
        )

    # -- VimSearchController host protocol --------------------------------

    def vim_search_corpus(self) -> str:
        return search_corpus(self.document)

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        scroll = self._body_scroll()
        return (int(scroll.scroll_x), int(scroll.scroll_y))

    def vim_search_overlay_viewport(self) -> SearchViewport:
        scroll = self._body_scroll()
        region = scroll.scrollable_content_region
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=region.width,
            height=region.height,
        )

    def vim_search_started(self) -> None:
        """No live refresh source to pause: the document is immutable."""

    def vim_search_exited(self, *, refresh: bool) -> None:
        """The body is already restored by ``vim_search_hide_overlay``."""

    def vim_search_show_overlay(self) -> None:
        self.query_one("#pager-search-command", Static).remove_class("hidden")

    def vim_search_hide_overlay(self) -> None:
        if self._body is not None:
            self.query_one("#pager-body", Static).update(self._body.renderable)
        command = self.query_one("#pager-search-command", Static)
        command.update("")
        command.add_class("hidden")

    def vim_search_paint_overlay(self, content: Text) -> None:
        self.query_one("#pager-body", Static).update(content)

    def vim_search_command_width(self) -> int:
        command = self.query_one("#pager-search-command", Static)
        return max(0, int(command.size.width) - 2)

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        command = self.query_one("#pager-search-command", Static)
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        def restore() -> None:
            self._body_scroll().scroll_to(x=x, y=y, animate=False, immediate=True)
            self._update_subject()

        self.call_after_refresh(restore)

    def vim_search_focus_overlay(self) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_focus_native(self) -> None:
        self.call_after_refresh(self._body_scroll().focus)

    def vim_search_notify(self, message: str) -> None:
        self.notify(message, severity="information")


__all__ = ["PagerExit", "SasePager"]
