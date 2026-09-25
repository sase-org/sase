"""Menu-select key handling for ``CommandLineScreen``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.command_line.chrome import CommandLineFrame
from sase.ace.tui.command_line.input import (
    CommandLineInput,
    binding_matches_key,
    command_line_keymaps_for,
)
from sase.ace.tui.command_line.popup import CommandLinePopup, PopupDecision
from sase.ace.tui.command_line.screen_constants import (
    COMMAND_LINE_MENU_HINTS,
    command_line_input_hints,
)

__all__ = ["CommandLineScreenKeysMixin"]


class CommandLineScreenKeysMixin:
    """zsh menu-select keys mixed into the command-line screen."""

    _history_search_active: bool
    _empty_state_active: bool

    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any: ...

    def command_line_handle_key(self, event: Any) -> bool:
        """Apply the zsh menu-select key rules; True when the key is consumed.

        The fixed menu keys (Tab, Shift-Tab, ``ctrl+n``/``ctrl+p``,
        ``ctrl+f``/Enter accept, Esc-leaves-menu) follow the zsh
        menu-select contract. History prev/next/search come from the live
        ``ace.keymaps.command_line`` scope instead of literals.
        """
        key = getattr(event, "key", None) or ""
        keymaps = command_line_keymaps_for(self)
        state = self._popup_state
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot complete.
            return False
        if state.typed_text != widget.text:
            # TextArea.Changed is queued separately from Key. A fast typist can
            # therefore press Tab after the widget has accepted text but before
            # its popup state has caught up. Resolve synchronously so Tab never
            # inserts a stale whole-command suggestion at the wrong span.
            self._refresh_completion()
            state = self._popup_state
        decision: PopupDecision | None = None
        prev_match = binding_matches_key(keymaps.history_prev, key)
        next_match = binding_matches_key(keymaps.history_next, key)
        if key == "tab":
            decision = state.on_tab()
        elif key == "shift+tab":
            decision = state.on_shift_tab()
        elif key == "ctrl+n":
            decision = state.on_ctrl_n()
        elif key == "ctrl+p":
            decision = state.on_ctrl_p()
        elif prev_match or next_match:
            if state.menu_active:
                decision = state.on_ctrl_n() if next_match else state.on_ctrl_p()
            else:
                self.history_step(1 if prev_match else -1)
                return True
        elif key == "ctrl+f":
            if not state.menu_active:
                return False
            decision = state.on_enter()
        elif key == "enter":
            if self._empty_state_active or self._history_search_active:
                return self._accept_stored_row()
            if not state.menu_active:
                return False
            decision = state.on_enter()
        elif key == "escape":
            if self._history_search_active:
                self._history_search_active = False
                self._refresh_completion()
                return True
            if not state.menu_active:
                return False
            decision = state.on_escape()
        elif binding_matches_key(keymaps.history_search, key):
            self.toggle_history_search()
            return True
        else:
            return False
        return self._apply_popup_decision(decision)

    def _apply_popup_decision(self, decision: PopupDecision) -> bool:
        """Apply a popup state-machine decision; always consumes the key."""
        action = decision.action
        if action in ("accept", "complete-prefix"):
            self._apply_popup_insert(decision.text or "")
            return True
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen cannot move.
            return True
        if action == "activate":
            popup.highlight_index(self._popup_state.index)
            self._render_popup_footer()
            self._render_signature()
            self._update_keys_hint()
            return True
        if action == "move":
            popup.highlight_index(self._popup_state.index)
            self._render_popup_footer()
            self._render_signature()
            return True
        if action == "leave-menu":
            try:
                widget = self.query_one(CommandLineInput)
                widget.set_line(decision.text or "")
            except Exception:  # noqa: BLE001 - teardown races degrade silently.
                pass
            try:
                popup.clear_highlight()
            except Exception:  # noqa: BLE001 - highlight clear is best effort.
                pass
            self._render_popup_footer()
            self._render_signature()
            self._update_keys_hint()
            return True
        return False

    def _apply_popup_insert(self, insert_text: str) -> None:
        """Replace the active slot span with the accepted completion."""
        state = self._popup_state
        try:
            widget = self.query_one(CommandLineInput)
        except Exception:  # noqa: BLE001 - unmounted screen cannot insert.
            return
        line = widget.text
        start = max(0, min(state.replace_start, len(line)))
        end = max(start, min(state.replace_end, len(line)))
        widget.text = line[:start] + insert_text + line[end:]
        try:
            widget.move_cursor((0, start + len(insert_text)))
        except Exception:  # noqa: BLE001 - cursor restore is best effort.
            pass
        state.menu_active = False
        state.index = 0

    def _update_keys_hint(self) -> None:
        """Switch the bottom-border hints between input and menu sets."""
        try:
            frame = self.query_one("#command-line-frame", CommandLineFrame)
        except Exception:  # noqa: BLE001 - unmounted screen cannot refresh.
            return
        if self._popup_state.menu_active:
            frame.set_key_hints(COMMAND_LINE_MENU_HINTS)
        else:
            frame.set_key_hints(
                command_line_input_hints(command_line_keymaps_for(self))
            )

    def on_option_list_option_selected(self, event: Any) -> None:
        """Accept a popup row picked with the mouse while the menu is live."""
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen ignores picks.
            return
        source = getattr(event, "option_list", getattr(event, "control", None))
        if source is not popup or not self._popup_state.menu_active:
            return
        highlighted = self._popup_state.highlighted
        if highlighted is None:
            return
        try:
            event.stop()
            event.prevent_default()
        except Exception:  # noqa: BLE001 - event control is best effort.
            pass
        self._apply_popup_insert(str(highlighted.get("insert_text", "")))

    def on_option_list_option_highlighted(self, event: Any) -> None:
        """Swap the signature row to the mouse-highlighted option's summary."""
        popup: CommandLinePopup
        try:
            popup = self.query_one(CommandLinePopup)
        except Exception:  # noqa: BLE001 - unmounted screen ignores highlights.
            return
        if getattr(event, "option_list", getattr(event, "control", None)) is not popup:
            return
        # Rule 12: the popup swallows echoes of its own programmatic highlights.
        index = popup.user_highlight_index(event)
        if index is None or not 0 <= index < len(self._popup_state.items):
            return
        if index != self._popup_state.index:
            self._popup_state.index = index
            self._render_popup_footer()
            self._render_signature()
