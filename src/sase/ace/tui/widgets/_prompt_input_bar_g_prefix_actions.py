"""Prompt ``g`` prefix dispatch and hint metadata for PromptInputBar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptGPrefixHintEntry,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


@dataclass(frozen=True)
class _PromptGPrefixBinding:
    """Declarative prompt ``g`` prefix binding metadata.

    One table drives both dispatch and the hint panel so the two cannot drift:
    ``action_name`` is the zero-arg method invoked on the second key,
    ``label_method_name`` renders the hint, and ``availability_method_name``
    gates whether the continuation is currently useful (and thus hinted).
    ``ctrl_g_only`` keeps a continuation on the prompt-local ``Ctrl+G`` surface
    without claiming the bare vim ``g`` prefix.
    """

    key: str
    action_name: str
    label_method_name: str
    availability_method_name: str
    uses_target_mode: bool = False
    ctrl_g_only: bool = False


_PROMPT_G_PREFIX_BINDINGS: tuple[_PromptGPrefixBinding, ...] = (
    _PromptGPrefixBinding(
        "d",
        "edit_definition_under_cursor",
        "_g_prefix_label_definition",
        "_g_prefix_available_definition",
    ),
    _PromptGPrefixBinding(
        "enter",
        "submit_active_pane",
        "_g_prefix_label_submit_active",
        "_g_prefix_available_submit_active",
    ),
    _PromptGPrefixBinding(
        "ctrl+c",
        "action_cancel_all",
        "_g_prefix_label_cancel_all",
        "_g_prefix_available_cancel_all",
        ctrl_g_only=True,
    ),
    _PromptGPrefixBinding(
        "j",
        "_g_focus_next_pane",
        "_g_prefix_label_focus_next",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "k",
        "_g_focus_prev_pane",
        "_g_prefix_label_focus_prev",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "J",
        "_g_move_pane_down",
        "_g_prefix_label_move_down",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "K",
        "_g_move_pane_up",
        "_g_prefix_label_move_up",
        "_g_prefix_available_pane_nav",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "-",
        "add_bottom_pane",
        "_g_prefix_label_add_pane",
        "_g_prefix_available_add_pane",
    ),
    _PromptGPrefixBinding(
        "=",
        "toggle_frontmatter_panel",
        "_g_prefix_label_frontmatter",
        "_g_prefix_available_frontmatter",
    ),
    _PromptGPrefixBinding(
        "s",
        "stash_all_panes",
        "_g_prefix_label_stash_all",
        "_g_prefix_available_stash_all",
    ),
    _PromptGPrefixBinding(
        "S",
        "request_update_pinned_stash",
        "_g_prefix_label_update_pin",
        "_g_prefix_available_update_pin",
    ),
    _PromptGPrefixBinding(
        "w",
        "request_write_xprompt",
        "_g_prefix_label_write_xprompt",
        "_g_prefix_available_write_xprompt",
    ),
    _PromptGPrefixBinding(
        "x",
        "request_save_as_xprompt",
        "_g_prefix_label_save_xprompt",
        "_g_prefix_available_save_xprompt",
    ),
    _PromptGPrefixBinding(
        "X",
        "convert_active_pane_to_local_xprompt",
        "_g_prefix_label_convert_local_xprompt",
        "_g_prefix_available_convert_local_xprompt",
        uses_target_mode=True,
    ),
    _PromptGPrefixBinding(
        "p",
        "request_open_prompt_stash",
        "_g_prefix_label_open_stash",
        "_g_prefix_available_stash_restore",
        ctrl_g_only=True,
    ),
)


class PromptInputBarGPrefixActionsMixin(_MixinBase):
    """Prompt ``g`` prefix keymaps and hint entry generation."""

    if TYPE_CHECKING:
        _mode: str
        _stack: PromptStackState

        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def action_cancel_all(self) -> None: ...
        def add_bottom_pane(self) -> None: ...
        def convert_active_pane_to_local_xprompt(
            self, *, target_mode: str = "normal"
        ) -> None: ...
        def focus_relative(self, delta: int, target_mode: str = "normal") -> bool: ...
        def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool: ...
        def request_open_prompt_stash(self) -> None: ...
        def request_save_as_xprompt(self) -> None: ...
        def request_write_xprompt(self) -> None: ...
        def request_update_pinned_stash(self) -> None: ...
        def stash_all_panes(self) -> None: ...
        def toggle_frontmatter_panel(self) -> None: ...

    def dispatch_g_prefix_key(
        self,
        key: str,
        *,
        target_mode: str = "normal",
        via_ctrl_g: bool = False,
    ) -> bool:
        """Dispatch the key following the prompt ``g`` prefix.

        Returns ``True`` when *key* is a prompt-specific ``g`` continuation
        (handled here, even if the action is a context no-op) so the caller can
        fall through to vim's own ``g`` commands (``gg``, ``ge``/``gE``,
        ``gu``/``gU``/``g~``) for anything not in this table.  Dispatch is keyed
        from the same table that feeds the hint panel, but it intentionally does
        not consult hint availability: each action method keeps its own
        prompt-mode / multi-pane guards, so an unavailable continuation is a
        harmless swallowed no-op.  ``target_mode`` only affects pane focus /
        reorder continuations; normal-mode callers keep the default while
        insert-mode ``Ctrl+G`` callers can keep the destination pane in INSERT.
        ``via_ctrl_g`` exposes continuations that belong only to the ``Ctrl+G``
        prefix, not bare vim ``g``.
        """
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.key != key:
                continue
            if binding.ctrl_g_only and not via_ctrl_g:
                continue
            action = getattr(self, binding.action_name, None)
            if callable(action):
                if binding.uses_target_mode:
                    action(target_mode=target_mode)
                else:
                    action()
            return True
        return False

    def g_prefix_hint_entries(
        self, *, via_ctrl_g: bool = False
    ) -> list[PromptGPrefixHintEntry]:
        """Return currently useful prompt ``g`` prefix entries for rendering."""
        entries: list[PromptGPrefixHintEntry] = []
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.ctrl_g_only and not via_ctrl_g:
                continue
            is_available = getattr(self, binding.availability_method_name)
            if not is_available():
                continue
            label = getattr(self, binding.label_method_name)()
            entries.append(PromptGPrefixHintEntry(binding.key, label))
        return entries

    def submit_active_pane(self) -> None:
        """Submit the active pane through the existing ``g<enter>`` path."""
        if self._mode != "prompt":
            return
        self.active_text_area().action_submit_prompt()

    def edit_definition_under_cursor(self) -> None:
        """Open the xprompt definition at the cursor in the bound stack."""
        if self._mode != "prompt":
            return
        action = getattr(self.active_text_area(), "_edit_definition_under_cursor", None)
        if callable(action):
            action()

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

    def _g_prefix_available_pane_nav(self) -> bool:
        """Whether ``gj``/``gk``/``gJ``/``gK`` apply to a real multi-pane stack."""
        return self._mode == "prompt" and len(self._stack) > 1

    def _g_prefix_available_submit_active(self) -> bool:
        """Whether ``g<enter>`` can submit the active prompt pane."""
        return self._mode == "prompt"

    def _g_prefix_available_definition(self) -> bool:
        if self._mode != "prompt":
            return False
        try:
            from sase.ace.tui.widgets._prompt_jump_target import (
                detect_jump_target_at_cursor,
            )

            text_area = self.active_text_area()
            offset = text_area._absolute_offset(text_area.cursor_location)
            target = detect_jump_target_at_cursor(text_area.text, offset)
            return target is not None and target.kind == "xprompt"
        except Exception:
            return False

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
        if self._mode != "prompt" or len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.items)

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
        return any(item.text.strip() for item in self._stack.items)

    def _g_prefix_available_save_xprompt(self) -> bool:
        """Whether ``gx`` can save the current prompt draft as an xprompt."""
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        return any(item.text.strip() for item in self._stack.items) or bool(
            self._stack.frontmatter.strip()
        )

    def _g_prefix_available_write_xprompt(self) -> bool:
        return (
            self._stack.binding is not None and self._g_prefix_available_save_xprompt()
        )

    def _g_prefix_available_convert_local_xprompt(self) -> bool:
        """Whether ``gX`` can convert the active pane into a local xprompt.

        Prompt mode only, and only when the active pane has non-blank text —
        the conversion stores that pane body as a local ``xprompts:`` helper, so
        an empty pane has nothing to save.
        """
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
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
        if len(self._stack) > 1:
            return "launch this pane"
        return "submit this draft"

    def _g_prefix_label_definition(self) -> str:
        return "edit definition"

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

    def _g_prefix_label_save_xprompt(self) -> str:
        """Return the ``gx`` label."""
        return "save as xprompt"

    def _g_prefix_label_write_xprompt(self) -> str:
        return "write xprompt" if self._stack.binding is not None else "save as xprompt"

    def _g_prefix_label_convert_local_xprompt(self) -> str:
        """Return the ``gX`` label."""
        return "save as local xprompt"

    def _g_prefix_label_open_stash(self) -> str:
        """Return the ``Ctrl+G p`` label."""
        return "stashed prompts…"
