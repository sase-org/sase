"""Prompt ``g`` prefix hint panel behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptGPrefixHintEntry,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarGPrefixHintsMixin(_MixinBase):
    """Transient which-key style hints for the prompt ``g`` prefix."""

    if TYPE_CHECKING:
        _g_prefix_hints_line_count: int
        _g_prefix_hints_signature: tuple[
            str, tuple[tuple[str, tuple[str, ...], str], ...]
        ]
        _g_prefix_hints_visible: bool

        def _update_height(self) -> None: ...
        def g_prefix_hint_entries(
            self, *, via_ctrl_g: bool = False
        ) -> list[PromptGPrefixHintEntry]: ...

    def show_g_prefix_hints(
        self,
        *,
        prefix_label: str = "g",
        include_editor: bool = False,
    ) -> None:
        """Render and reveal the prompt prefix hint panel if useful."""
        entries = self.g_prefix_hint_entries(via_ctrl_g=(prefix_label == "^G"))
        if include_editor:
            entries = [
                PromptGPrefixHintEntry("g", "edit in editor", ("ctrl+g",)),
                *entries,
            ]
        if not entries:
            self.hide_g_prefix_hints()
            return

        entry_signature = tuple(
            (entry.key, entry.aliases, entry.label) for entry in entries
        )
        signature = (prefix_label, entry_signature)
        if self._g_prefix_hints_visible and signature == self._g_prefix_hints_signature:
            return

        try:
            panel = self.query_one("#prompt-g-prefix-hints", Static)
        except Exception:
            return

        content = self._render_g_prefix_hints(entries, prefix_label=prefix_label)
        panel.border_title = f" {prefix_label} "
        panel.border_subtitle = "\\[esc] cancel"
        panel.update(content)
        panel.remove_class("hidden")

        line_count = len(content.plain.splitlines()) if content.plain else 0
        old_line_count = self._g_prefix_hints_line_count
        was_visible = self._g_prefix_hints_visible
        self._g_prefix_hints_visible = True
        self._g_prefix_hints_signature = signature
        self._g_prefix_hints_line_count = line_count + 3
        if not was_visible or self._g_prefix_hints_line_count != old_line_count:
            self._update_height()

    def hide_g_prefix_hints(self) -> None:
        """Hide the prompt ``g`` prefix hint panel."""
        if not self._g_prefix_hints_visible:
            return
        try:
            panel = self.query_one("#prompt-g-prefix-hints", Static)
        except Exception:
            return

        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.add_class("hidden")
        self._g_prefix_hints_visible = False
        self._g_prefix_hints_signature = ("", ())
        self._g_prefix_hints_line_count = 0
        self._update_height()

    @staticmethod
    def _render_g_prefix_hints(
        entries: list[PromptGPrefixHintEntry],
        *,
        prefix_label: str,
    ) -> Text:
        """Build Rich text for the prompt prefix hint rows."""
        content = Text()
        for index, entry in enumerate(entries):
            content.append("  ")
            for key_index, key in enumerate((entry.key, *entry.aliases)):
                if key_index:
                    content.append(" / ")
                content.append(prefix_label, style="dim #87D7FF")
                content.append(
                    PromptInputBarGPrefixHintsMixin._display_g_prefix_key(key),
                    style="bold #00D7AF",
                )
            content.append("   ")
            content.append(entry.label)
            if index < len(entries) - 1:
                content.append("\n")
        return content

    @staticmethod
    def _display_g_prefix_key(key: str) -> str:
        """Return the visible continuation label for a prompt ``g`` key."""
        if key == "enter":
            return "<enter>"
        if key.startswith("ctrl+") and len(key.removeprefix("ctrl+")) == 1:
            return f"^{key[-1].upper()}"
        return key
