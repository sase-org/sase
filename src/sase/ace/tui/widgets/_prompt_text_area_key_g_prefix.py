"""PromptTextArea ``Ctrl+G`` prefix handling.

The prompt-local ``^G`` prefix (hint panel, editor entry, and prompt-specific
continuations) is shared by INSERT-mode ``Ctrl+G`` and NORMAL-mode ``Ctrl+G``.
The vim ``g`` pending path is untouched; this mixin owns a separate prefix
state so ``Ctrl+G`` can shadow the app-level binding in both modes.

Prompt-stack pane focus / reorder, add-pane, and the frontmatter panel toggle
live on this prefix rather than on dedicated insert-mode chords:

- ``gj`` / ``gk`` focus the next / previous pane and ``gJ`` / ``gK`` reorder
  the active pane (dispatched through the vim ``g`` pending state in
  ``_handle_normal_pending_key``). Bare normal-mode ``J`` is therefore free
  again for vim's line join, and normal-mode ``K`` is handled by the vim
  dispatcher as a preview lookup command. Normal-mode ``Up`` / ``Down`` fall
  through to the TextArea's own cursor movement in both single- and
  multi-pane stacks.
- ``g-`` appends a new empty bottom pane (``add_bottom_pane``) and ``g=``
  toggles the frontmatter panel (``toggle_frontmatter_panel``). The old
  insert-mode structural chords (``Ctrl+-`` / ``ctrl+underscore`` and
  ``Ctrl+Shift+=``) no longer fire from the key dispatcher; insert-mode users
  reach the same prompt-local table through the ``Ctrl+G`` prefix. The
  structural actions still clear transient completion state internally, just
  as the old chord handlers did before mutating the stack.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.events import Key

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


def _resolve_g_prefix_second_key(event: Key) -> str:
    """Return the canonical key used to dispatch a prompt ``g`` continuation."""
    character = event.character
    if character and len(character) == 1 and character.isprintable():
        return character
    return event.key


class PromptTextAreaKeyGPrefixMixin(_MixinBase):
    """INSERT- and NORMAL-mode ``Ctrl+G`` prompt-local prefix handling."""

    if TYPE_CHECKING:
        _insert_g_prefix_pending: bool
        _normal_g_prefix_pending: bool
        _vim_mode: str

        def _clear_insert_g_prefix(self) -> None: ...
        def _clear_normal_g_prefix(self) -> None: ...
        def _find_prompt_bar(self) -> Any: ...
        def _show_insert_g_prefix_hints(self) -> None: ...
        def _show_normal_g_prefix_hints(self) -> None: ...
        def action_open_editor(self) -> None: ...

    def _handle_insert_g_prefix_key(self, event: Key) -> bool:
        """Handle the INSERT-mode ``Ctrl+G`` prompt-local prefix."""
        if self._vim_mode != "insert":
            self._clear_insert_g_prefix()
            return False

        if not self._insert_g_prefix_pending:
            if event.key != "ctrl+g":
                return False
            self._insert_g_prefix_pending = True
            self._show_insert_g_prefix_hints()
            return True

        if event.key == "escape":
            self._clear_insert_g_prefix()
            return True

        key = _resolve_g_prefix_second_key(event)
        if key == "g" or event.key == "ctrl+g":
            self._clear_insert_g_prefix()
            self.action_open_editor()
            return True

        self._clear_insert_g_prefix()
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            dispatch(key, target_mode="insert", via_ctrl_g=True)
        return True

    def _handle_normal_g_prefix_key(self, event: Key) -> bool:
        """Handle the NORMAL-mode ``Ctrl+G`` prompt-local prefix.

        Mirrors :meth:`_handle_insert_g_prefix_key` so NORMAL-mode ``Ctrl+G``
        opens the same prompt-local ``^G`` prefix (hint panel, editor entry, and
        prompt-specific continuations) that INSERT-mode ``Ctrl+G`` does, while
        still shadowing the app-level ``Ctrl+G`` binding. The only behavioral
        difference is that continuations dispatch with ``target_mode="normal"``
        so pane focus / reorder land in NORMAL mode, matching the vim ``g``
        prefix. The vim ``g`` pending path is untouched; this is its own state.
        """
        if self._vim_mode != "normal":
            self._clear_normal_g_prefix()
            return False

        if not self._normal_g_prefix_pending:
            if event.key != "ctrl+g":
                return False
            self._normal_g_prefix_pending = True
            self._show_normal_g_prefix_hints()
            return True

        if event.key == "escape":
            self._clear_normal_g_prefix()
            return True

        key = _resolve_g_prefix_second_key(event)
        if key == "g" or event.key == "ctrl+g":
            self._clear_normal_g_prefix()
            self.action_open_editor()
            return True

        self._clear_normal_g_prefix()
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            dispatch(key, target_mode="normal", via_ctrl_g=True)
        return True
