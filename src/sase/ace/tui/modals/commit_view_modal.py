"""Scrollable commit message and diff modal."""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.actions.clipboard import copy_to_system_clipboard
from sase.ace.tui.util.lazy_syntax import LazySyntaxRenderCache, lazy_renderable
from sase.ace.tui.widgets.prompt_panel._agent_commits import load_commit_diff_text
from sase.ace.tui.widgets.prompt_panel._agent_deltas import parse_unified_diff_deltas
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec

from .base import CopyModeForwardingMixin


_COLOR_HEADER = "bold #87D7FF"
_COLOR_SUBJECT = "bold #D7D7FF"
_COLOR_SHA = "dim #D7D7AF"
_COLOR_BODY = "#D7D7FF"
_COLOR_ADDED = "bold #5FD787"
_COLOR_MODIFIED = "bold #FFD787"
_COLOR_REMOVED = "bold #FF5F5F"
_COLOR_MUTED = "dim #87D7FF"


class CommitViewModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Present a commit's full message and pretty diff."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_sha", "Copy SHA"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(self, spec: CommitViewSpec) -> None:
        super().__init__()
        self._spec = spec
        self._syntax_render_cache = LazySyntaxRenderCache()
        self._diff_loaded = False
        self._diff_text: str | None = None
        self._diff_worker: Worker[str | None] | None = None

    def compose(self) -> ComposeResult:
        with Container(id="commit-view-container"):
            yield Static(self._build_title(), id="commit-view-title")
            with VerticalScroll(id="commit-view-scroll"):
                yield Static(self._build_content(), id="commit-view-content")
            yield Static(
                "j/k scroll | ctrl+d/u page | g/G top/bottom | y copy sha | esc close",
                id="commit-view-footer",
            )

    def on_mount(self) -> None:
        self._diff_worker = self.run_worker(
            lambda: load_commit_diff_text(self._spec),
            thread=True,
            exclusive=True,
            exit_on_error=False,
            group="commit-view-diff",
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._diff_worker:
            return
        if event.state not in {
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        }:
            return
        self._diff_worker = None
        if event.state == WorkerState.SUCCESS:
            self._diff_text = event.worker.result
        else:
            self._diff_text = None
        self._diff_loaded = True
        if not self.is_attached:
            return
        self.query_one("#commit-view-content", Static).update(self._build_content())

    def _build_title(self) -> Text:
        text = Text()
        text.append("COMMIT", style="bold #FFD700")
        text.append("  ")
        text.append(self._spec.repo_name, style=_COLOR_HEADER)
        if self._spec.is_primary:
            text.append(" (primary)", style="bold #5FD787")
        text.append("  ")
        text.append(self._spec.short_sha or self._spec.sha, style=_COLOR_SHA)
        if self._spec.subject:
            text.append(" - ")
            text.append(self._spec.subject, style="bold white")
        if self._spec.diff_path:
            text.append("\n")
            text.append(self._spec.diff_path, style=_COLOR_MUTED)
        return text

    def _build_content(self) -> RenderableType:
        parts: list[RenderableType] = [self._build_message_header(self._diff_text)]
        parts.append(Text("-" * 72, style="dim"))
        if not self._diff_loaded:
            parts.append(Text("Loading diff...", style="dim italic #87D7FF"))
        elif self._diff_text:
            parts.append(
                lazy_renderable(
                    self._diff_text,
                    "diff",
                    line_numbers=True,
                    theme="monokai",
                    render_cache=self._syntax_render_cache,
                )
            )
        else:
            parts.append(
                Text(
                    "Diff unavailable for this commit.",
                    style="dim italic #87D7FF",
                )
            )
        return Group(*parts)

    def _build_message_header(self, diff_text: str | None) -> Text:
        text = Text()
        text.append("Message\n", style=_COLOR_HEADER)
        subject, body = _split_message(self._spec.message, self._spec.subject)
        text.append(subject or "(message unavailable)", style=_COLOR_SUBJECT)
        text.append("\n")
        if body:
            text.append(body.rstrip(), style=_COLOR_BODY)
            text.append("\n")
        summary = _format_change_summary(diff_text)
        if summary is not None:
            text.append("\n")
            text.append_text(summary)
        text.append("\n")
        return text

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_sha(self) -> None:
        sha = self._spec.sha or self._spec.short_sha
        if copy_to_system_clipboard(sha):
            self.notify("Copied commit SHA to clipboard")
        else:
            self.notify("Failed to copy to clipboard", severity="error")

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#commit-view-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


def _split_message(message: str, fallback_subject: str) -> tuple[str, str]:
    lines = message.splitlines()
    for idx, line in enumerate(lines):
        subject = line.strip()
        if not subject:
            continue
        body = "\n".join(lines[idx + 1 :]).strip("\n")
        return subject, body
    return fallback_subject, ""


def _format_change_summary(diff_text: str | None) -> Text | None:
    if not diff_text:
        return None
    entries = parse_unified_diff_deltas(diff_text)
    if not entries:
        return None
    added, modified, removed, binary = _line_totals(entries)
    summary = Text()
    summary.append("Changes: ", style=_COLOR_HEADER)
    summary.append(f"+{added}", style=_COLOR_ADDED)
    summary.append(" ")
    summary.append(f"~{modified}", style=_COLOR_MODIFIED)
    summary.append(" ")
    summary.append(f"-{removed}", style=_COLOR_REMOVED)
    if binary:
        summary.append(" binary", style="dim italic #808080")
    suffix = "file" if len(entries) == 1 else "files"
    summary.append(f" - {len(entries)} {suffix}", style=_COLOR_MUTED)
    return summary


def _line_totals(entries: list[DeltaEntry]) -> tuple[int, int, int, bool]:
    added = 0
    modified = 0
    removed = 0
    binary = False
    for entry in entries:
        if entry.line_stats is None:
            continue
        added += entry.line_stats.added
        modified += entry.line_stats.modified
        removed += entry.line_stats.removed
        binary = binary or entry.line_stats.binary
    return added, modified, removed, binary


__all__ = ["CommitViewModal"]
