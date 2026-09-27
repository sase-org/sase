"""Failure-report modal for the red updates gear.

Opened by clicking the red gear (or the ``f`` Update-panel row in a later
phase). Reports the journal's recorded failure: what ran, how it failed,
and the tail of its output. ``u`` jumps to the Update panel, ``d``
dismisses the recorded failure, and ``y`` copies the report.
"""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace._update_attempts_model import UpdateFailure
from sase.ace.tui.update_gear import format_failure_when
from sase.ace.tui.widgets.update_accents import UPDATE_FAILED_ACCENT

from ..actions.clipboard import schedule_copy_delivery
from .base import CopyModeForwardingMixin

UpdateFailureChoice = Literal["dismiss", "open_update"]


class UpdateFailureModal(
    CopyModeForwardingMixin, ModalScreen[UpdateFailureChoice | None]
):
    """Show one recorded update failure with its output tail."""

    BINDINGS = [
        ("u", "open_update", "Open Update"),
        ("d", "dismiss_failure", "Dismiss"),
        ("y", "copy_report", "Copy"),
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("g", "scroll_to_top", "Top"),
        ("G", "scroll_to_bottom", "Bottom"),
    ]

    def __init__(self, failure: UpdateFailure) -> None:
        super().__init__()
        self._failure = failure

    @property
    def failure(self) -> UpdateFailure:
        """The recorded failure this report covers."""
        return self._failure

    def compose(self) -> ComposeResult:
        failure = self._failure
        when = format_failure_when(failure.finished_at)
        verb = "interrupted" if failure.interrupted else "failed"
        if failure.interrupted:
            headline = (
                f'ACE exited before "{failure.label}" finished; '
                "the install may be incomplete."
            )
        else:
            headline = failure.error
        body = (
            Text(failure.output_tail)
            if failure.output_tail
            else Text("No output was captured.", style="dim")
        )
        with Container(id="update-failure-container"):
            yield Static(
                Text(f"{failure.label} · {failure.stage} · {verb} {when}", style="dim"),
                id="update-failure-meta",
            )
            yield Static(
                Text(headline, style=f"bold {UPDATE_FAILED_ACCENT}"),
                id="update-failure-error",
            )
            yield Static(
                Text("── last output ──", style="dim"),
                id="update-failure-output-label",
            )
            with VerticalScroll(id="update-failure-scroll"):
                yield Static(body, id="update-failure-body")
            yield Static(
                Text("u open Update · d dismiss · y copy · q close", style="dim"),
                id="update-failure-footer",
            )

    def on_mount(self) -> None:
        title = (
            "✗ Update interrupted" if self._failure.interrupted else "✗ Update failed"
        )
        container = self.query_one("#update-failure-container", Container)
        container.border_title = Text(title, style=f"bold {UPDATE_FAILED_ACCENT}")

    def action_open_update(self) -> None:
        self.dismiss("open_update")

    def action_dismiss_failure(self) -> None:
        self.dismiss("dismiss")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_report(self) -> None:
        schedule_copy_delivery(
            self,
            self._copy_text(),
            copied_label="update failure report",
            task_name="sase-copy-update-failure-report",
        )

    def _copy_text(self) -> str:
        parts = [self._failure.error]
        if self._failure.output_tail:
            parts.append(self._failure.output_tail)
        return "\n\n".join(parts)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#update-failure-scroll", VerticalScroll)
        scroll.scroll_relative(y=scroll.scrollable_content_region.height // 2)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#update-failure-scroll", VerticalScroll)
        scroll.scroll_relative(y=-(scroll.scrollable_content_region.height // 2))

    def action_scroll_to_top(self) -> None:
        self.query_one("#update-failure-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def action_scroll_to_bottom(self) -> None:
        self.query_one("#update-failure-scroll", VerticalScroll).scroll_end(
            animate=False
        )


__all__ = ["UpdateFailureChoice", "UpdateFailureModal"]
