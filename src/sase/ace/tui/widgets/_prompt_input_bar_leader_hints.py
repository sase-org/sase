"""Comma-leader hint panel behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    PromptLeaderHintEntry,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarLeaderHintsMixin(_MixinBase):
    """Transient which-key style hints for the prompt comma leader."""

    if TYPE_CHECKING:
        _leader_hints_line_count: int
        _leader_hints_signature: tuple[tuple[str, str], ...]
        _leader_hints_visible: bool

        def _update_height(self) -> None: ...
        def leader_hint_entries(self) -> list[PromptLeaderHintEntry]: ...

    def show_leader_hints(self) -> None:
        """Render and reveal the prompt comma-leader hint panel if useful."""
        entries = self.leader_hint_entries()
        if not entries:
            self.hide_leader_hints()
            return

        signature = tuple((entry.key, entry.label) for entry in entries)
        if self._leader_hints_visible and signature == self._leader_hints_signature:
            return

        try:
            panel = self.query_one("#prompt-leader-hints", Static)
        except Exception:
            return

        content = self._render_leader_hints(entries)
        panel.border_title = " leader "
        panel.border_subtitle = "\\[esc] cancel"
        panel.update(content)
        panel.remove_class("hidden")

        line_count = len(content.plain.splitlines()) if content.plain else 0
        old_line_count = self._leader_hints_line_count
        was_visible = self._leader_hints_visible
        self._leader_hints_visible = True
        self._leader_hints_signature = signature
        self._leader_hints_line_count = line_count + 3
        if not was_visible or self._leader_hints_line_count != old_line_count:
            self._update_height()

    def hide_leader_hints(self) -> None:
        """Hide the prompt comma-leader hint panel."""
        if not self._leader_hints_visible:
            return
        try:
            panel = self.query_one("#prompt-leader-hints", Static)
        except Exception:
            return

        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.add_class("hidden")
        self._leader_hints_visible = False
        self._leader_hints_signature = ()
        self._leader_hints_line_count = 0
        self._update_height()

    @staticmethod
    def _render_leader_hints(entries: list[PromptLeaderHintEntry]) -> Text:
        """Build Rich text for the prompt comma-leader hint rows."""
        content = Text()
        for index, entry in enumerate(entries):
            content.append("  ")
            content.append(",", style="dim #87D7FF")
            content.append(entry.key, style="bold #00D7AF")
            content.append("   ")
            content.append(entry.label)
            if index < len(entries) - 1:
                content.append("\n")
        return content
