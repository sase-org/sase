"""Prompt ``g`` prefix continuation actions for PromptInputBar."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


__all__ = ["PromptGPrefixContinuationsMixin"]


class PromptGPrefixContinuationsMixin(_MixinBase):
    """Implementations behind each prompt ``g`` prefix continuation."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def active_text_area(self) -> PromptTextArea: ...
        def focus_relative(self, delta: int, target_mode: str = "normal") -> bool: ...
        def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool: ...

    def submit_active_pane(self) -> None:
        """Submit the active pane through the existing ``g<enter>`` path."""
        if self._mode != "prompt":
            return
        self.active_text_area().action_submit_prompt()

    def edit_definition_under_cursor(self) -> None:
        """Open the xprompt definition at the cursor in the bound stack."""
        if self._mode != "prompt" or self._stack.selected_item.is_auxiliary_pane:
            return
        action = getattr(self.active_text_area(), "_edit_definition_under_cursor", None)
        if callable(action):
            action()

    def format_active_prompt(self) -> None:
        """Format the pane that is active when this action is invoked."""
        if self._stack.selected_item.is_auxiliary_pane:
            return
        text_area = self.active_text_area()
        if not text_area.text:
            return
        action = getattr(text_area, "format_prompt_markdown", None)
        if callable(action):
            action()

    def request_open_glossary_panel(self) -> None:
        """Ask the app to open the Memory panel on the glossary term under the cursor.

        Presentation-only: the bar resolves the glossary term under the
        cursor (if any) to its ``glossary:<slug>`` memory-web identity and
        posts ``GlossaryPanelRequested`` with that identity and the bar's
        current mode. The app opens the Memory subtab seeded with that
        identity and restores prompt focus and vim mode on dismiss (boundary
        rule D6).
        """
        self.post_message(
            self.GlossaryPanelRequested(  # type: ignore[attr-defined]
                self._glossary_note_identity_under_cursor(),
                self._mode,
            )
        )

    def request_open_snippets_panel(self) -> None:
        """Ask the app to open the snippets panel.

        Presentation-only: the bar captures a bare snippet trigger or
        ``#[trigger]`` under the cursor (if any) without I/O and posts
        ``SnippetPanelRequested`` with that trigger and the bar's current
        mode. The app opens the panel and restores prompt focus, vim mode,
        selection, and cursor on dismiss (boundary rule D6).
        """
        self.post_message(
            self.SnippetPanelRequested(  # type: ignore[attr-defined]
                self._snippet_trigger_under_cursor(),
                self._mode,
            )
        )

    def _snippet_trigger_under_cursor(self) -> str | None:
        """Return the snippet trigger at the cursor, if resolvable without I/O."""
        try:
            from sase.snippet.cursor import snippet_trigger_at_offset

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            known = getattr(self.app, "_snippets_cache", None)
            if not isinstance(known, dict):
                known = getattr(self.app, "_user_snippets", None)
            if not isinstance(known, dict):
                known = None
            return snippet_trigger_at_offset(text_area.text, offset, known)
        except Exception:
            return None

    def request_open_memory_panel(self) -> None:
        """Ask the app to open the memory panel.

        Presentation-only: the bar captures the ``#memory/<stem>`` xprompt
        reference under the cursor (if any) and posts
        ``MemoryPanelRequested`` with that reference and the bar's current
        mode. The app opens the panel and restores prompt focus and vim
        mode on dismiss (boundary rule D6).
        """
        self.post_message(
            self.MemoryPanelRequested(  # type: ignore[attr-defined]
                self._memory_note_under_cursor(),
                self._mode,
            )
        )

    def _glossary_note_identity_under_cursor(self) -> str | None:
        """Return the ``glossary:<slug>`` identity for the term at the cursor.

        Reuses the prompt-area ``lookup_glossary_span`` match used by the
        glossary preview action, deriving the strand slug from its already
        in-memory source path so this stays disk-read-free on the event
        loop. A cold or missing catalog, or a term with no source path, is a
        miss: the Memory panel loads its own catalog and opens on the
        seeded scope's first note.
        """
        try:
            match = self.active_text_area()._glossary_match_under_cursor(schedule=False)
        except Exception:
            return None
        if not isinstance(match, tuple) or len(match) != 3:
            return None
        source = getattr(match[2], "source", None)
        source_path = source.get("source_path") if isinstance(source, Mapping) else None
        if not isinstance(source_path, str) or not source_path:
            return None
        slug = Path(source_path).stem
        return f"glossary:{slug}" if slug else None

    def _memory_note_under_cursor(self) -> str | None:
        """Return the ``#memory/<stem>`` reference at the cursor, if any.

        Reuses the prompt-area jump-target detection used by definition
        jumps. A non-memory xprompt, a nested path, or a miss is ``None``:
        the panel loads its own catalog and opens on the seeded scope's
        first note.
        """
        try:
            from sase.ace.tui.widgets._prompt_jump_target import (
                detect_jump_target_at_cursor,
            )

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            target = detect_jump_target_at_cursor(text_area.text, offset)
        except Exception:
            return None
        if target is None or getattr(target, "kind", None) != "xprompt":
            return None
        name = str(getattr(target, "target", "") or "")
        if name.startswith("#"):
            name = name[1:]
        if not name.startswith("memory/"):
            return None
        stem = name.removeprefix("memory/")
        if stem.endswith(".md"):
            stem = stem[: -len(".md")]
        if not stem or "/" in stem or stem.lower() == "readme":
            return None
        return f"#memory/{stem}"

    def _g_focus_next_pane(self, *, target_mode: str = "normal") -> None:
        """Focus the next/lower pane (the ``gj`` keymap)."""
        self.focus_relative(1, target_mode=target_mode)

    def _g_focus_prev_pane(self, *, target_mode: str = "normal") -> None:
        """Focus the previous/higher pane (the ``gk`` keymap)."""
        self.focus_relative(-1, target_mode=target_mode)

    def _g_move_pane_down(self, *, target_mode: str = "normal") -> None:
        """Move the active pane lower/later (the ``gJ`` keymap)."""
        self.move_active_pane(1, target_mode=target_mode)

    def _g_move_pane_up(self, *, target_mode: str = "normal") -> None:
        """Move the active pane higher/earlier (the ``gK`` keymap)."""
        self.move_active_pane(-1, target_mode=target_mode)

    def open_recent_file_history(self) -> None:
        """Open the recent-files history menu (the ``Ctrl+G r`` keymap)."""
        if self._mode != "prompt" or self._stack.selected_item.is_auxiliary_pane:
            return
        action = getattr(self.active_text_area(), "_try_file_history_completion", None)
        if callable(action):
            action()
