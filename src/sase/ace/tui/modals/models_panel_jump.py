"""Adaptive apostrophe entry-jump for Launch Control.

Adapts the shared :class:`KeyedPaneEntryJumpMixin` state machine to
:class:`~sase.ace.tui.modals.models_panel.ModelsPanel`'s rows. The state
machine itself -- hint allocation, the pending-prefix matcher, and the
bounded back stack -- is unchanged; this module only supplies the small host
hooks that describe Launch Control's current selectable rows and routes raw
hint keystrokes to them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual import events

from sase.ace.tui.actions.navigation.jump_hints import normalize_jump_key

from .pane_entry_jump import KeyedPaneEntryJumpMixin


class ModelsPanelJumpMixin(KeyedPaneEntryJumpMixin[str]):
    """Adapt the shared entry-jump state machine to Launch Control's rows.

    Hints land on whatever :attr:`_row_by_id` (built by
    :class:`ModelsPanelDisplayMixin` for the currently active scope) holds,
    so a hint session always matches the settings, aliases, or bucket members
    on screen -- at the top level or drilled into a bucket.
    """

    if TYPE_CHECKING:
        _row_by_id: dict[str, Any]

        def _highlighted_row_id(self) -> str | None: ...

        def _replace_display(self, *, keep: str | None = None) -> None: ...

    # -- jump host hooks ------------------------------------------------

    def _jump_target_keys(self) -> list[str]:
        """Return the active scope's selectable row ids in visual order."""
        return list(self._row_by_id)

    def _jump_current_key(self) -> str | None:
        return self._highlighted_row_id()

    def _jump_select_key(self, key: str) -> None:
        # Jump mode is already cleared by the time this runs (see
        # ``PaneEntryJumpMixin._perform_jump``), so this repaint renders the
        # normal, hint-free rows and lands the highlight on ``key``.
        self._replace_display(keep=key)

    def _jump_repaint(self) -> None:
        self._replace_display(keep=self._highlighted_row_id())

    # -- key routing ------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Intercept jump-mode keypresses before modal bindings run."""
        if not self.jump_mode_active:
            return
        key = normalize_jump_key(event.key, event.character)
        if self.handle_jump_key(key):
            event.prevent_default()
            event.stop()


__all__ = ["ModelsPanelJumpMixin"]
