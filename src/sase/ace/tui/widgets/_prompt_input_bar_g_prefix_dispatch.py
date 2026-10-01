"""Prompt ``g`` prefix binding table and dispatch for PromptInputBar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptGPrefixHintEntry,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


__all__ = ["PromptGPrefixDispatchMixin"]


@dataclass(frozen=True)
class _PromptGPrefixBinding:
    """Declarative prompt ``g`` prefix binding metadata.

    One table drives both dispatch and the hint panel so the two cannot drift:
    ``action_name`` is the zero-arg method invoked on the second key,
    ``label_method_name`` renders the hint, and ``availability_method_name``
    gates whether the continuation is currently useful (and thus hinted).
    ``ctrl_g_only`` keeps a continuation on the prompt-local ``Ctrl+G`` surface
    without claiming the bare vim ``g`` prefix. ``ctrl_g_aliases`` adds alternate
    continuations to that surface without duplicating the action or hint row.
    """

    key: str
    action_name: str
    label_method_name: str
    availability_method_name: str
    uses_target_mode: bool = False
    ctrl_g_only: bool = False
    ctrl_g_aliases: tuple[str, ...] = ()


_PROMPT_G_PREFIX_BINDINGS: tuple[_PromptGPrefixBinding, ...] = (
    _PromptGPrefixBinding(
        "d",
        "edit_definition_under_cursor",
        "_g_prefix_label_definition",
        "_g_prefix_available_definition",
    ),
    _PromptGPrefixBinding(
        "f",
        "format_active_prompt",
        "_g_prefix_label_format_prompt",
        "_g_prefix_available_format_prompt",
    ),
    _PromptGPrefixBinding(
        "G",
        "request_open_glossary_panel",
        "_g_prefix_label_glossary",
        "_g_prefix_available_glossary",
    ),
    _PromptGPrefixBinding(
        "m",
        "request_open_memory_panel",
        "_g_prefix_label_memory",
        "_g_prefix_available_memory",
    ),
    _PromptGPrefixBinding(
        "D",
        "request_dispatch_target_picker",
        "_g_prefix_label_dispatch_target",
        "_g_prefix_available_dispatch_target",
    ),
    _PromptGPrefixBinding(
        "b",
        "request_launch_tab_picker",
        "_g_prefix_label_launch_tab",
        "_g_prefix_available_launch_tab",
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
        "t",
        "request_snippet_target_pane",
        "_g_prefix_label_snippet_target",
        "_g_prefix_available_snippet_target",
        ctrl_g_aliases=("ctrl+t",),
    ),
    _PromptGPrefixBinding(
        "T",
        "request_open_snippets_panel",
        "_g_prefix_label_snippets",
        "_g_prefix_available_snippets",
    ),
    _PromptGPrefixBinding(
        "w",
        "request_write_xprompt",
        "_g_prefix_label_write_xprompt",
        "_g_prefix_available_write_xprompt",
    ),
    _PromptGPrefixBinding(
        "x",
        "request_mini_xprompt_target_pane",
        "_g_prefix_label_mini_xprompt_target",
        "_g_prefix_available_mini_xprompt_target",
        ctrl_g_aliases=("ctrl+x",),
    ),
    _PromptGPrefixBinding(
        "X",
        "request_save_as_xprompt",
        "_g_prefix_label_save_xprompt",
        "_g_prefix_available_save_xprompt",
    ),
    _PromptGPrefixBinding(
        "L",
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
    _PromptGPrefixBinding(
        "r",
        "open_recent_file_history",
        "_g_prefix_label_recent_files",
        "_g_prefix_available_recent_files",
        ctrl_g_only=True,
    ),
)


class PromptGPrefixDispatchMixin(_MixinBase):
    """Prompt ``g`` prefix dispatch and hint entry generation."""

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
        ``gu``/``gU``/``g~``) for anything not in this table.  ``gm`` is claimed
        here and is unclaimed by the text area's vim ``g`` handling.  Dispatch
        is keyed from the same table that feeds the hint panel, but it
        intentionally does not consult hint availability: each action method
        keeps its own prompt-mode / multi-pane guards, so an unavailable
        continuation is a harmless swallowed no-op.  ``target_mode`` only
        affects pane focus / reorder continuations; normal-mode callers keep
        the default while insert-mode ``Ctrl+G`` callers can keep the
        destination pane in INSERT. ``via_ctrl_g`` exposes continuations that
        belong only to the ``Ctrl+G`` prefix, not bare vim ``g``.
        """
        for binding in _PROMPT_G_PREFIX_BINDINGS:
            if binding.key != key and not (
                via_ctrl_g and key in binding.ctrl_g_aliases
            ):
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
            aliases = binding.ctrl_g_aliases if via_ctrl_g else ()
            entries.append(PromptGPrefixHintEntry(binding.key, label, aliases))
        return entries
