"""Adaptive ``'`` entry jump for the Admin Center Updates pane.

The Updates pane hosts three sub-tabs behind one widget, so its jump adapter
dispatches on the active sub-tab: the logical row list is the active list's
*item* rows (disabled group headers are never jump targets).  Core hosts no
list at all, so it reports zero targets and ``'`` is a silent no-op there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import RenderableType
from textual import events
from textual.widgets import OptionList

from ..actions.navigation.jump_hints import normalize_jump_key
from .pane_entry_jump import PaneEntryJumpMixin

if TYPE_CHECKING:
    from .config_center_session import UpdatesSubTab


class PluginsBrowserJumpMixin(PaneEntryJumpMixin):
    """Wire the Updates pane's active sub-tab list onto the shared jump mixin."""

    if TYPE_CHECKING:
        _active_subtab: UpdatesSubTab

        def _active_option_list(self) -> OptionList | None: ...

        def _agent_cli_hints(self) -> str: ...

        def _is_item(self, option_list: OptionList, index: int) -> bool: ...

        def _rebuild_options(self) -> None: ...

        def _repaint_agent_cli_options(self) -> None: ...

        def _update_static(self, selector: str, content: RenderableType) -> None: ...

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
        """Option indices of the active list's item rows, headers excluded."""
        option_list = self._active_option_list()
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
        option_list = self._active_option_list()
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
        # ``_detail_name`` dedup guard, and both selection guards behave
        # normally.
        self._jump_repaint()
        option_list = self._active_option_list()
        item_indices = self._jump_item_option_indices()
        if option_list is None or not 0 <= index < len(item_indices):
            return
        option_list.highlighted = item_indices[index]

    def _jump_repaint(self) -> None:
        if self._active_subtab == "plugins":
            # ``_rebuild_options`` refreshes the plugins hint line itself.
            self._rebuild_options()
        elif self._active_subtab == "agent-clis":
            self._repaint_agent_cli_options()
            self._update_static("#agent-clis-hints", self._agent_cli_hints())


__all__ = ["PluginsBrowserJumpMixin"]
