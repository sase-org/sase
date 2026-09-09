"""The `?` Trail & keys sheet for the link-traversing pager."""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.tui.modals.trail_strip import TrailStripEntry
from sase.pager._trail_chrome import (
    PagerTrailSnapshot,
    build_pager_help_content,
    render_pager_help_footer,
    render_pager_help_header,
)


def _pager_help_text(
    *,
    section_total: int,
    label_count: int = 0,
    trail_entries: Sequence[TrailStripEntry] = (),
    trail_snapshot: PagerTrailSnapshot | None = None,
    width: int = 88,
) -> Text:
    """Build the complete key/trail sheet as text, pure and Textual-free."""

    del trail_entries
    header = render_pager_help_header(
        trail_snapshot=trail_snapshot,
        width=width,
    )
    body = build_pager_help_content(
        section_total=section_total,
        label_count=label_count,
        trail_snapshot=trail_snapshot,
        width=width,
    )
    text = Text()
    text.append_text(header)
    text.append("\n\n")
    text.append_text(body.text)
    return text


class PagerHelpScreen(ModalScreen[None]):
    """Scrollable Trail & keys modal, dismissed by the same keys as close."""

    BINDINGS = [
        Binding("q,escape,question_mark", "dismiss_help", "Close"),
        Binding("j,down", "scroll_line_down", "Down", show=False),
        Binding("k,up", "scroll_line_up", "Up", show=False),
        Binding("ctrl+d", "scroll_page_down", "Page Down", show=False),
        Binding("ctrl+u", "scroll_page_up", "Page Up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
    ]

    def __init__(
        self,
        *,
        section_total: int,
        label_count: int = 0,
        trail_entries: Sequence[TrailStripEntry] = (),
        trail_snapshot: PagerTrailSnapshot | None = None,
    ) -> None:
        super().__init__()
        del trail_entries
        self._section_total = section_total
        self._label_count = label_count
        self._trail_snapshot = trail_snapshot
        self._current_line = 0
        self._content_signature: tuple[int, int, object | None] | None = None

    def compose(self) -> ComposeResult:
        with Container(id="pager-help"):
            yield Static(id="pager-help-header")
            with VerticalScroll(id="pager-help-scroll"):
                yield Static(id="pager-help-content")
            yield Static(id="pager-help-footer")

    def on_mount(self) -> None:
        self._refresh_content()
        scroll = self._help_scroll()
        scroll.can_focus = True
        self.call_after_refresh(self._reveal_current_visit)

    def on_resize(self, _event: Resize) -> None:
        self._refresh_content()
        self.call_after_refresh(self._reveal_current_visit)

    def action_dismiss_help(self) -> None:
        self.dismiss(None)

    def action_scroll_line_down(self) -> None:
        self._help_scroll().scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        self._help_scroll().scroll_relative(y=-1, animate=False)

    def action_scroll_page_down(self) -> None:
        scroll = self._help_scroll()
        scroll.scroll_relative(y=max(1, scroll.size.height // 2), animate=False)

    def action_scroll_page_up(self) -> None:
        scroll = self._help_scroll()
        scroll.scroll_relative(y=-max(1, scroll.size.height // 2), animate=False)

    def action_scroll_top(self) -> None:
        self._help_scroll().scroll_to(y=0, animate=False, immediate=True)

    def action_scroll_bottom(self) -> None:
        scroll = self._help_scroll()
        scroll.scroll_to(y=scroll.max_scroll_y, animate=False, immediate=True)

    def _refresh_content(self) -> None:
        width = self._content_width()
        signature = (
            width,
            self._section_total,
            self._trail_snapshot.signature
            if self._trail_snapshot is not None
            else None,
        )
        if signature == self._content_signature:
            return
        self._content_signature = signature

        header = render_pager_help_header(
            trail_snapshot=self._trail_snapshot,
            width=width,
        )
        body = build_pager_help_content(
            section_total=self._section_total,
            label_count=self._label_count,
            trail_snapshot=self._trail_snapshot,
            width=width,
        )
        footer = render_pager_help_footer(width=width)
        self._current_line = body.current_line
        self.query_one("#pager-help-header", Static).update(header)
        self.query_one("#pager-help-content", Static).update(body.text)
        self.query_one("#pager-help-footer", Static).update(footer)

    def _reveal_current_visit(self) -> None:
        scroll = self._help_scroll()
        target = max(0, self._current_line - 2)
        scroll.scroll_to(y=target, animate=False, immediate=True)
        scroll.focus()

    def _content_width(self) -> int:
        width = int(self.size.width)
        if width <= 0:
            width = 88
        return max(12, min(88, width - 8))

    def _help_scroll(self) -> VerticalScroll:
        return self.query_one("#pager-help-scroll", VerticalScroll)


__all__ = ["PagerHelpScreen", "_pager_help_text"]
