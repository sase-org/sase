"""Prompt ``g`` prefix hint availability and labels for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarGPrefixHintMetadataMixin(_MixinBase):
    """Availability gates and labels behind the prompt ``g`` hint panel."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...

    def _g_prefix_available_pane_nav(self) -> bool:
        """Whether ``gj``/``gk``/``gJ``/``gK`` apply to a real multi-pane stack."""
        return self._mode == "prompt" and len(self._stack) > 1

    def _g_prefix_available_submit_active(self) -> bool:
        """Whether ``g<enter>`` can submit the active prompt pane."""
        return self._mode == "prompt"

    def _g_prefix_available_definition(self) -> bool:
        if self._mode != "prompt" or self._stack.selected_item.is_auxiliary_pane:
            return False
        try:
            from sase.ace.tui.widgets._prompt_jump_target import (
                detect_jump_target_at_cursor,
            )

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            known_skills = (
                text_area._get_warm_macro_skill_names()
                if "/" in text_area.text
                else frozenset()
            )
            target = detect_jump_target_at_cursor(
                text_area.text,
                offset,
                known_skills=known_skills,
            )
            return target is not None and target.kind == "macro"
        except Exception:
            return False

    def _g_prefix_available_format_prompt(self) -> bool:
        """Whether the active prompt-style pane contains text to format."""
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        try:
            return bool(self.active_text_area().text.strip())
        except Exception:
            return False

    def _g_prefix_available_glossary(self) -> bool:
        """Whether ``gG`` / ``^GG`` can open the glossary panel."""
        return self._mode == "prompt"

    def _g_prefix_available_memory(self) -> bool:
        """Whether ``gm`` / ``^Gm`` can open the memory panel."""
        return self._mode == "prompt"

    def _g_prefix_available_dispatch_target(self) -> bool:
        """Whether ``gD`` / ``^GD`` can open the dispatch target picker."""
        return (
            self._mode == "prompt" and not self._stack.selected_item.is_auxiliary_pane
        )

    def _g_prefix_available_launch_tab(self) -> bool:
        """Whether ``gb`` / ``^Gb`` can open the Launch Tab picker."""
        return (
            self._mode == "prompt" and not self._stack.selected_item.is_auxiliary_pane
        )

    def _g_prefix_available_snippets(self) -> bool:
        """Whether ``gT`` / ``^GT`` can open the snippets panel."""
        return self._mode == "prompt"

    def _g_prefix_available_cancel_all(self) -> bool:
        """Whether ``Ctrl+G Ctrl+C`` can cancel the whole prompt stack."""
        return self._mode == "prompt"

    def _g_prefix_available_add_pane(self) -> bool:
        """Whether ``g-`` can append a bottom pane (prompt mode only)."""
        return self._mode == "prompt"

    def _g_prefix_available_frontmatter(self) -> bool:
        """Whether ``g=`` can toggle the prompt frontmatter panel."""
        return self._mode == "prompt"

    def _g_prefix_available_stash_all(self) -> bool:
        """Whether ``gs`` would capture at least one pane in a real stack."""
        if self._mode != "prompt" or self._stack.agent_count <= 1:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items)

    def _g_prefix_available_stash_restore(self) -> bool:
        """Whether ``Ctrl+G p`` has a restorable prompt stash in this app."""
        if self._mode != "prompt":
            return False
        try:
            checker = getattr(self.app, "_has_stashed_prompts", None)
            return bool(checker()) if callable(checker) else False
        except Exception:
            return False

    def _g_prefix_available_update_pin(self) -> bool:
        """Whether ``gS`` can save the current draft over a pinned stash."""
        if self._mode != "prompt":
            return False
        try:
            checker = getattr(self.app, "_has_pinned_stashed_prompts", None)
            has_pin = bool(checker()) if callable(checker) else False
        except Exception:
            return False
        if not has_pin:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items)

    def _g_prefix_available_snippet_target(self) -> bool:
        """Whether ``gt`` can open or retarget a snippet target pane."""
        return self._mode == "prompt"

    def _g_prefix_available_mini_macro_target(self) -> bool:
        """Whether ``gx`` can open or retarget a mini-macro target pane."""
        return self._mode == "prompt"

    def _g_prefix_available_save_macro(self) -> bool:
        """Whether ``gX`` can open the whole-stack save-as panel."""
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.agent_items) or bool(
            self._stack.frontmatter.strip()
        )

    def _g_prefix_available_write_macro(self) -> bool:
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        return self._stack.binding is not None and self._g_prefix_available_save_macro()

    def _g_prefix_available_convert_local_macro(self) -> bool:
        """Whether ``gL`` can convert the active pane into a local macro.

        Prompt mode only, and only when the active pane has non-blank text —
        the conversion stores that pane body as a local ``macros:`` helper, so
        an empty pane has nothing to save.
        """
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if self._stack.selected_item.is_auxiliary_pane:
            return False
        return bool(self._stack.selected_item.text.strip())

    def _g_prefix_label_focus_next(self) -> str:
        """Return the ``gj`` label."""
        return "focus next pane"

    def _g_prefix_label_focus_prev(self) -> str:
        """Return the ``gk`` label."""
        return "focus prev pane"

    def _g_prefix_label_move_down(self) -> str:
        """Return the ``gJ`` label."""
        return "move pane down"

    def _g_prefix_label_move_up(self) -> str:
        """Return the ``gK`` label."""
        return "move pane up"

    def _g_prefix_label_submit_active(self) -> str:
        """Return the context-sensitive ``g<enter>`` label."""
        if self._stack.selected_item.is_snippet_pane:
            return "save snippet"
        if self._stack.selected_item.is_mini_macro_pane:
            return "save mini-macro"
        if self._stack.agent_count > 1:
            return "launch this pane"
        return "submit this draft"

    def _g_prefix_label_definition(self) -> str:
        return "edit definition"

    def _g_prefix_label_format_prompt(self) -> str:
        return "format prompt"

    def _g_prefix_label_glossary(self) -> str:
        return "glossary…"

    def _g_prefix_label_memory(self) -> str:
        return "memory…"

    def _g_prefix_label_dispatch_target(self) -> str:
        return "launch target…"

    def _g_prefix_label_launch_tab(self) -> str:
        return "launch tab…"

    def _g_prefix_label_snippets(self) -> str:
        return "snippets…"

    def _g_prefix_label_cancel_all(self) -> str:
        """Return the ``Ctrl+G Ctrl+C`` label."""
        return "cancel all panes"

    def _g_prefix_label_add_pane(self) -> str:
        """Return the ``g-`` label."""
        return "add pane"

    def _g_prefix_label_frontmatter(self) -> str:
        """Return the ``g=`` label."""
        return "toggle frontmatter"

    def _g_prefix_label_stash_all(self) -> str:
        """Return the ``gs`` label."""
        return "stash all panes"

    def _g_prefix_label_update_pin(self) -> str:
        """Return the ``gS`` label."""
        return "update pinned stash"

    def _g_prefix_label_snippet_target(self) -> str:
        """Return the ``gt`` label."""
        snippet = self._stack.snippet_item
        if snippet is not None and snippet.snippet_target is not None:
            return f"rename ⇥ {snippet.snippet_target.trigger}…"
        return "new / edit snippet…"

    def _g_prefix_label_mini_macro_target(self) -> str:
        """Return the ``gx`` label."""
        mini = self._stack.mini_macro_item
        if mini is not None and mini.mini_macro_target is not None:
            return f"retarget #{mini.mini_macro_target.name}…"
        return "new / edit mini-macro…"

    def _g_prefix_label_save_macro(self) -> str:
        """Return the ``gX`` label."""
        return "save as macro/snippet"

    def _g_prefix_label_write_macro(self) -> str:
        readonly = getattr(self, "_readonly_macro_target", None)
        if readonly is not None:
            return f"save as {readonly.reference}"
        binding = self._stack.binding
        if binding is not None:
            return f"save {binding.reference}"
        return "save as macro"

    def _g_prefix_label_convert_local_macro(self) -> str:
        """Return the ``gL`` label."""
        return "save as local macro"

    def _g_prefix_label_open_stash(self) -> str:
        """Return the ``Ctrl+G p`` label."""
        return "stashed prompts…"

    def _g_prefix_label_recent_files(self) -> str:
        """Return the ``Ctrl+G r`` label."""
        return "recent files"

    def _g_prefix_available_recent_files(self) -> bool:
        """Whether ``Ctrl+G r`` can open recent files from the active pane."""
        return (
            self._mode == "prompt" and not self._stack.selected_item.is_auxiliary_pane
        )
