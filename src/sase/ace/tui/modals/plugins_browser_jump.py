"""Adaptive ``'`` entry jump for the Admin Center Updates pane.

The Updates pane hosts one list over every domain, so the logical row list
is that list's *item* rows (disabled section headers are never jump
targets).  ``'`` allocates hints across core packages, plugins, and agent
CLIs in one space.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events

from ..actions.navigation.jump_hints import normalize_jump_key
from .pane_entry_jump import PaneEntryJumpMixin

if TYPE_CHECKING:
    from textual.widgets import OptionList


class PluginsBrowserJumpMixin(PaneEntryJumpMixin):
    """Wire the Updates pane's merged list onto the shared jump mixin."""

    if TYPE_CHECKING:

        def _is_item(self, option_list: OptionList, index: int) -> bool: ...

        def _option_list(self) -> OptionList | None: ...

        def _rebuild_options(self, *, reuse_options: bool = False) -> None: ...

    def on_key(self, event: events.Key) -> None:
        """Give jump mode, then a bare ``'``, first refusal at *event*."""
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key == "apostrophe":
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()

    def reset_jump_state(self, *, repaint: bool = False) -> None:
        """Leave jump mode and drop the back stack before the rows change.

        *repaint* redraws the current rows, which callers must request when
        they are not about to rebuild those rows themselves.
        """
        if repaint and self.jump_mode_active:
            self.exit_jump_mode()
        self.invalidate_jump_hints(identities_changed=True, target_count=0)

    # -- host hooks ----------------------------------------------------------

    def _jump_item_option_indices(self) -> list[int]:
        """Option indices of the list's item rows, headers excluded."""
        option_list = self._option_list()
        if option_list is None:
            return []
        return [
            index
            for index in range(option_list.option_count)
            if self._is_item(option_list, index)
        ]

    def _jump_target_count(self) -> int:
        return len(self._jump_item_option_indices())

    def _jump_current_index(self) -> int | None:
        option_list = self._option_list()
        if option_list is None or option_list.highlighted is None:
            return None
        item_indices = self._jump_item_option_indices()
        if option_list.highlighted not in item_indices:
            return None
        return item_indices.index(option_list.highlighted)

    def _jump_select_index(self, index: int) -> None:
        # Repaint first so the hint prefixes are gone before the highlight
        # moves, then select by assigning ``highlighted`` exactly the way
        # ``action_next_option`` does, so the detail debouncer, the
        # ``_detail_key`` dedup guard, and the selection guard behave
        # normally.
        self._jump_repaint()
        option_list = self._option_list()
        item_indices = self._jump_item_option_indices()
        if option_list is None or not 0 <= index < len(item_indices):
            return
        option_list.highlighted = item_indices[index]

    def _jump_repaint(self) -> None:
        self._rebuild_options()


__all__ = ["PluginsBrowserJumpMixin"]
