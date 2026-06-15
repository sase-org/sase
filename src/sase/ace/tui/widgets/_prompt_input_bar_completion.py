"""Completion panel behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import DirectiveCompletionMetadata
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    append_input_hints,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarCompletionMixin(_MixinBase):
    """Completion panel, soft-completion subtitle, and argument hint rendering."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_visible: bool
        _mode_subtitle: str
        _soft_completion_visible: bool

        def _update_height(self) -> None: ...

    def show_file_completions(
        self,
        token: str,
        rows: list[CompletionCandidate],
        selected_index: int,
        scroll_offset: int = 0,
        completion_kind: str = "file",
    ) -> None:
        """Show the path/xprompt completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: "file" for path completion, "xprompt" for xprompt.
        """
        panel = self.query_one("#prompt-completion", Static)
        total = len(rows)
        visible = rows[scroll_offset : scroll_offset + MAX_VISIBLE]

        is_xprompt = completion_kind == "xprompt"
        is_directive = completion_kind == "directive"
        is_history = completion_kind == "file_history"
        is_arg_completion = completion_kind in ("xprompt_arg_name", "xprompt_arg_value")
        content = Text()
        for i, candidate in enumerate(visible):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected_index

            if is_selected:
                content.append("\u25b8 ", style="bold")
            else:
                content.append("  ")

            if is_xprompt:
                self._append_xprompt_completion_row(content, candidate, is_selected)
            elif is_directive:
                self._append_directive_completion_row(content, candidate, is_selected)
            elif is_arg_completion:
                content.append(
                    candidate.display,
                    style="bold yellow" if is_selected else "yellow",
                )
            elif candidate.is_dir:
                content.append("\U0001f4c1 ")
                content.append(
                    candidate.display, style="bold cyan" if is_selected else "cyan"
                )
            else:
                content.append("\U0001f4c4 ")
                content.append(candidate.display, style="bold" if is_selected else "")

            if i < len(visible) - 1:
                content.append("\n")

        remaining = total - (scroll_offset + len(visible))
        if remaining > 0:
            content.append(f"\n  \u2193 {remaining} more\u2026", style="dim")

        # Border title: "xprompts" for xprompt completion, "recent files"
        # for file-history completion, directory for file.
        if is_xprompt:
            panel.border_title = "xprompts"
        elif is_directive:
            panel.border_title = "directives"
        elif completion_kind == "xprompt_arg_name":
            panel.border_title = "xprompt arg names"
        elif completion_kind == "xprompt_arg_value":
            panel.border_title = "xprompt arg values"
        elif completion_kind == "xprompt_arg_path":
            panel.border_title = "xprompt path"
        elif is_history:
            panel.border_title = "recent files"
        elif "/" in token:
            panel.border_title = token[: token.rindex("/") + 1]
        else:
            panel.border_title = token

        if is_history:
            panel.border_subtitle = "[^L] accept  [^D] delete"
        else:
            panel.border_subtitle = ""

        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3  # +3 for panel border + margin
        self._update_height()

    def _append_xprompt_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one xprompt completion row using assist metadata when present."""
        content.append(
            candidate.display,
            style="bold green" if is_selected else "green",
        )
        entry = (
            candidate.metadata
            if isinstance(candidate.metadata, XPromptAssistEntry)
            else None
        )
        if entry is None:
            return

        kind = "skill" if entry.is_skill else entry.kind
        content.append(f"  {kind}", style="dim")
        if entry.description:
            content.append(f"  {entry.description}", style="dim")
        append_input_hints(content, entry.inputs)

    def _append_directive_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one prompt directive completion row."""
        content.append(
            candidate.display,
            style="bold magenta" if is_selected else "magenta",
        )
        metadata = (
            candidate.metadata
            if isinstance(candidate.metadata, DirectiveCompletionMetadata)
            else None
        )
        if metadata is None:
            return

        details: list[str] = []
        if metadata.argument_hint:
            details.append(metadata.argument_hint)
        if metadata.aliases:
            details.append(
                "alias " + ", ".join(f"%{alias}" for alias in metadata.aliases)
            )
        if metadata.description:
            details.append(metadata.description)
        if details:
            content.append(f"  {'  '.join(details)}", style="dim")

    def hide_file_completions(self) -> None:
        """Hide the path completion panel."""
        panel = self.query_one("#prompt-completion", Static)
        panel.update("")
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_line_count = 0
        self._update_height()

    def set_prompt_mode_subtitle(self, subtitle: str) -> None:
        """Set the prompt mode subtitle, preserving any visible soft suggestion."""
        self._mode_subtitle = subtitle
        if not self._soft_completion_visible:
            self.border_subtitle = subtitle

    def show_soft_completion(self, suggestion: PromptSoftCompletion) -> None:
        """Render a soft completion in the prompt bar subtitle."""
        display = suggestion.display.replace("\n", " ").strip()
        if len(display) > 48:
            display = f"{display[:45]}..."
        self._soft_completion_visible = True
        self.border_subtitle = f"[^L] accept {display}"

    def hide_soft_completion(self) -> None:
        """Restore the mode subtitle when no soft completion is visible."""
        if not self._soft_completion_visible:
            return
        self._soft_completion_visible = False
        self.border_subtitle = self._mode_subtitle

    def show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Show the post-accept xprompt argument hint panel."""
        panel = self.query_one("#prompt-completion", Static)
        content = Text()
        content.append(hint.reference_text, style="bold green")
        content.append(" arguments", style="dim")
        append_input_hints(
            content,
            hint.entry.inputs,
            active_index=hint.active_input_index,
            include_descriptions=True,
        )

        panel.border_title = "xprompt args"
        panel.border_subtitle = "[:] colon  [(] named args"
        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = line_count + 3
        self._update_height()
