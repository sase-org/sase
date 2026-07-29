"""Scrollable full-screen modal for a structured notification report."""

from __future__ import annotations

import os
import subprocess

from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.axe.chop_report_render import TONE_STYLES, render_chop_report
from sase.notifications import NotificationReport, format_relative_time

_DEFAULT_REPORT_WIDTH = 100


class ReportModal(ModalScreen[None]):
    """Display one resolved report with vim-style scrolling."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
        ("y", "copy_path", "Copy path"),
        ("e", "open_in_editor", "Edit"),
    ]

    def __init__(self, report: NotificationReport) -> None:
        super().__init__()
        self._report = report

    def compose(self) -> ComposeResult:
        with Container(id="report-modal-container"):
            yield Static(self._build_title(), id="report-title")
            with VerticalScroll(id="report-scroll"):
                yield Static(
                    self._build_content(_DEFAULT_REPORT_WIDTH),
                    id="report-content",
                )
            yield Static(
                "Ctrl+D/U scroll | j/k line | g/G top/bottom | "
                "y copy path | e edit | Esc/q close",
                id="report-footer",
            )

    def on_mount(self) -> None:
        self.call_after_refresh(self._refresh_content)

    def on_resize(self, _event: events.Resize) -> None:
        self._refresh_content()

    def _build_title(self) -> Text:
        text = Text("📊 REPORT", style=f"bold {TONE_STYLES['info']}")
        text.append("  ")
        text.append(self._report.title, style="bold white")
        if self._report.updated_at:
            age = format_relative_time(self._report.updated_at)
            if self._report.source == "live":
                text.append(f"\nlive · updated {age}", style=TONE_STYLES["ok"])
            else:
                text.append(
                    f"\nsnapshot · captured {age}",
                    style=TONE_STYLES["muted"],
                )
        if self._report.path:
            text.append(f"\n{self._report.path}", style="dim #87D7FF")
        return text

    def _build_content(self, width: int) -> RenderableType:
        document = self._report.document
        if document is None:
            return Text(
                self._report.error or "Report could not be loaded",
                style=TONE_STYLES["error"],
            )
        return render_chop_report(document, width=width)

    def _refresh_content(self) -> None:
        try:
            scroll = self.query_one("#report-scroll", VerticalScroll)
            content = self.query_one("#report-content", Static)
        except Exception:
            return
        width = scroll.scrollable_content_region.width
        content.update(
            self._build_content(width if width > 0 else _DEFAULT_REPORT_WIDTH)
        )

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#report-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#report-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        self.query_one("#report-scroll", VerticalScroll).scroll_relative(
            y=1,
            animate=False,
        )

    def action_scroll_line_up(self) -> None:
        self.query_one("#report-scroll", VerticalScroll).scroll_relative(
            y=-1,
            animate=False,
        )

    def action_scroll_top(self) -> None:
        self.query_one("#report-scroll", VerticalScroll).scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        self.query_one("#report-scroll", VerticalScroll).scroll_end(animate=False)

    def action_copy_path(self) -> None:
        if not self._report.path:
            self.notify(
                "Snapshot reports do not have a file path",
                severity="warning",
            )
            return
        schedule_copy_delivery(
            self,
            self._report.path,
            copied_label=f"report path ({self._report.path})",
            task_name="sase-copy-report-path",
        )

    def action_open_in_editor(self) -> None:
        if not self._report.path:
            self.notify(
                "Snapshot reports do not have a file to edit",
                severity="warning",
            )
            return
        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [self._report.path])
        with self.app.suspend():
            subprocess.run(editor_args, check=False)


__all__ = ["ReportModal"]
