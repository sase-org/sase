"""Scrollable output pane for one repeatable gate action.

A ``run_command`` action returns a closed display record; when it carries a
non-empty ``body`` the reviewer sees it here, rendered in the format the
action declared. The gate underneath stays pending and answerable — closing
this modal returns to the still-open gate review.
"""

from __future__ import annotations

import json

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ..actions.clipboard import schedule_copy_delivery
from ..util.frontmatter_syntax import markdown_document_syntax
from .base import CopyModeForwardingMixin


class GateActionOutputModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Show one action's output without answering the gate."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_output", "Copy"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(self, *, title: str, body: str, display_format: str = "text") -> None:
        super().__init__()
        self._title = title
        self._body = body
        self._display_format = display_format

    def compose(self) -> ComposeResult:
        with Container(id="gate-action-output-container"):
            yield Static(
                Text(self._title, style="bold cyan"),
                id="gate-action-output-title",
                classes="gate-review-header",
            )
            scroll = VerticalScroll(
                id="gate-action-output-scroll", classes="gate-review-document"
            )
            with scroll:
                yield Static(self._rendered_body(), id="gate-action-output-body")
            yield Static(
                Text("y copy  q close  Ctrl+D/U / g / G to scroll", style="dim"),
                id="gate-action-output-footer",
                classes="gate-review-footer",
            )

    def _rendered_body(self) -> RenderableType:
        if self._display_format == "markdown":
            return markdown_document_syntax(self._body)
        if self._display_format == "json":
            try:
                return Text(json.dumps(json.loads(self._body), indent=2))
            except (TypeError, ValueError):
                return Text(self._body)
        return Text(self._body)

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_output(self) -> None:
        schedule_copy_delivery(
            self,
            self._body,
            copied_label="action output",
            task_name="sase-copy-gate-action-output",
        )

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#gate-action-output-scroll", VerticalScroll)
        scroll.scroll_relative(y=scroll.scrollable_content_region.height // 2)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#gate-action-output-scroll", VerticalScroll)
        scroll.scroll_relative(y=-(scroll.scrollable_content_region.height // 2))

    def action_scroll_to_top(self) -> None:
        self.query_one("#gate-action-output-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#gate-action-output-scroll", VerticalScroll).scroll_end(
            animate=False
        )


__all__ = ["GateActionOutputModal"]
