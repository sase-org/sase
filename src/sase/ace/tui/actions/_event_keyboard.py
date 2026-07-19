"""Keyboard and input event handlers for the ACE TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events

from ._event_base import EventHandlersBase
from .navigation.jump_hints import normalize_jump_key

if TYPE_CHECKING:
    from textual.widgets import Input, TextArea


class EventKeyboardMixin(EventHandlersBase):
    """Mixin providing key and text-input event handlers."""

    def on_key(self, event: events.Key) -> None:
        """Handle key events, including fold, checkout, copy, and ancestry sub-keys."""
        self._last_input_action = event.key
        self._record_input_event()
        metadata_search_handler = getattr(
            self,
            "_handle_agent_metadata_search_key",
            None,
        )
        if callable(metadata_search_handler) and metadata_search_handler(event):
            event.prevent_default()
            event.stop()
            return
        member_jump_handler = getattr(self, "_handle_member_jump_key", None)
        key = normalize_jump_key(event.key, event.character)
        if (
            getattr(self, "_member_jump_pending_digit", None) is not None
            and callable(member_jump_handler)
            and member_jump_handler(key)
        ):
            event.prevent_default()
            event.stop()
            return
        if self._entry_jump_mode_active:
            if self._handle_entry_jump_key(key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._fold_mode_active:
            if self._handle_fold_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._checkout_mode_active:
            if self._handle_checkout_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._copy_mode_active:
            if self._handle_copy_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif (
            self._ancestor_mode_active
            or self._child_mode_active
            or self._sibling_mode_active
        ):
            if self._handle_ancestry_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._leader_mode_active:
            if self._handle_leader_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._bang_mode_active:
            if self._handle_bang_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif self._custom_mode_active is not None:
            if self._handle_custom_mode_key(event.key):  # type: ignore[attr-defined]
                event.prevent_default()
                event.stop()
        elif event.key in self._custom_mode_prefixes:
            self._custom_mode_active = self._custom_mode_prefixes[event.key]
            self._update_custom_mode_footer(self._custom_mode_active)  # type: ignore[attr-defined]
            event.prevent_default()
            event.stop()
        elif event.key == "escape":
            exit_panel_focus = getattr(self, "_exit_expanded_panel_focus", None)
            if callable(exit_panel_focus) and exit_panel_focus():
                event.prevent_default()
                event.stop()
        elif callable(member_jump_handler) and member_jump_handler(key):
            event.prevent_default()
            event.stop()

    def on_input_changed(self, _event: Input.Changed) -> None:
        """Record activity when user types in a focused Input widget.

        Textual's ``Input`` widget calls ``event.stop()`` on key events,
        preventing them from bubbling to the App's ``on_key()`` handler.
        The ``Input.Changed`` message still bubbles, so we catch it here
        to keep input-quiescence timing accurate while the user types.
        """
        self._last_input_action = "input_changed"
        self._record_input_event()

    def on_text_area_changed(self, _event: TextArea.Changed) -> None:
        """Record activity when user types in a focused TextArea widget.

        ``VimTextArea``-based editors inherit Textual's ``TextArea.Changed``
        message. Recording that message keeps the same input-quiescence timing
        that plain ``Input`` widgets had before conversion.
        """
        self._last_input_action = "text_area_changed"
        self._record_input_event()
