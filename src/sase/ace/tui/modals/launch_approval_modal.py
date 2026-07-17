"""Launch approval modal for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.notification_gates.debug import GateDebugContext

from .base import CopyModeForwardingMixin


@dataclass
class LaunchApprovalResult:
    """Result from the launch approval modal."""

    action: str
    feedback: str | None = None


class LaunchApprovalModal(
    CopyModeForwardingMixin, ModalScreen[LaunchApprovalResult | None]
):
    """Modal for reviewing and approving/rejecting an agent launch request."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("d", "debug_view", "Debug"),
        ("a", "approve", "Approve"),
        ("r", "reject", "Reject"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(
        self,
        *,
        preview_file: str | None,
        request_id: str | None,
        debug_context: GateDebugContext | None = None,
    ) -> None:
        super().__init__()
        self._preview_file = preview_file
        self._request_id = request_id
        self._debug_context = debug_context

    def compose(self) -> ComposeResult:
        hints = (
            "[green]a[/green]=Approve  [red]r[/red]=Reject  "
            "[cyan]d[/cyan]=Debug  [dim]q[/dim]=Cancel  |  Ctrl+D/U / g / G to scroll"
        )
        with Container(id="launch-approval-container"):
            yield Static(self._title_markup(), id="launch-approval-title")

            with VerticalScroll(id="launch-approval-scroll"):
                syntax = Syntax(
                    self._read_preview(),
                    "markdown",
                    theme="monokai",
                    word_wrap=True,
                )
                yield Static(syntax, id="launch-approval-content")

            yield Static(hints, id="launch-approval-footer")

    def action_approve(self) -> None:
        self.dismiss(LaunchApprovalResult(action="approve"))

    def action_reject(self) -> None:
        self.dismiss(LaunchApprovalResult(action="reject"))

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_debug_view(self) -> None:
        from .gate_debug_modal import show_gate_debug

        show_gate_debug(self, self._debug_context)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#launch-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#launch-approval-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_scroll_to_top(self) -> None:
        scroll = self.query_one("#launch-approval-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_to_bottom(self) -> None:
        scroll = self.query_one("#launch-approval-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)

    def _title_markup(self) -> str:
        request = self._request_id or "(unknown request)"
        return f"[bold cyan]Launch Review[/bold cyan]  [dim]{request}[/dim]"

    def _read_preview(self) -> str:
        if not self._preview_file:
            return "No launch preview file was attached."
        try:
            return Path(self._preview_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            return f"[Error reading launch preview: {exc}]"
