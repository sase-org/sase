"""Shared helpers for leader-mode keymap tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agent_workflow._entry_points import EntryPointsMixin
from sase.ace.tui.actions.agent_workflow._leader_mode import LeaderModeMixin
from sase.ace.tui.actions.agents._unread_state import (
    BulkUnreadToggleOutcome,
    _BulkUnreadToggleResult,
)
from sase.ace.tui.actions.patch._core import PatchMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.widgets import KeybindingFooter


class _FakeApp(LeaderModeMixin, PatchMixin):
    """Minimal app stand-in for leader dispatch."""

    def __init__(
        self,
        *,
        patches: list[Any] | None = None,
        current_tab: str = "patches",
    ) -> None:
        self.patches = patches or []
        self.current_idx = 0
        self.current_tab = current_tab  # type: ignore[assignment]
        self.marked_indices = set()
        self._agents = []
        self._marked_agents: set[Any] = set()
        self.kill_and_edit_count = 0
        self.bulk_kill_and_edit_count = 0
        self.kill_and_edit_last_count = 0
        self._leader_mode_active = True
        self._last_leader_key: str | None = None
        self._keymap_registry = load_keymap_registry({})
        self.pushed_modals: list[Any] = []
        self.notifications: list[str] = []
        self.refresh_count = 0
        self.toggle_panel_grouping_count = 0
        self.toggle_selected_panels_count = 0
        self.agent_footer_refresh_count = 0
        self.retry_edit_count = 0
        self.runners_count = 0
        self.revert_count = 0
        self.jump_unread_count = 0
        self.jump_unread_result = True
        self.jump_stopped_count = 0
        self.jump_stopped_result = True
        self.full_history_refresh_count = 0
        self.mark_all_unread_count = 0
        self.mark_all_unread_result = _BulkUnreadToggleResult(
            BulkUnreadToggleOutcome.MARKED_READ,
            2,
        )
        self.prompt_history_calls: list[dict[str, bool]] = []
        self.home_agent_count = 0
        self.quick_patch_agent_count = 0
        self.quick_selected_agent_count = 0
        self.marked_agent_run_count = 0
        self.update_sase_shortcut_count = 0
        self.jump_to_last_error_count = 0
        self.open_prompt_stash_count = 0
        self.edit_query_count = 0
        self.show_help_count = 0
        self.scheduled_callbacks: list[Any] = []

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        del callback
        self.pushed_modals.append(modal)

    def notify(self, message: str, **_: Any) -> None:
        self.notifications.append(message)

    def call_later(self, callback: Any) -> None:
        self.scheduled_callbacks.append(callback)

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def action_toggle_agent_panel_grouping(self) -> None:
        self.toggle_panel_grouping_count += 1

    def action_toggle_selected_agent_panels(self) -> None:
        self.toggle_selected_panels_count += 1

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.agent_footer_refresh_count += 1

    def _retry_edit_agent(self) -> None:
        self.retry_edit_count += 1

    def action_show_runners(self) -> None:
        self.runners_count += 1

    def _start_revert_selected_agent(self) -> None:
        self.revert_count += 1

    def _jump_to_next_unread_done_agent(self) -> bool:
        self.jump_unread_count += 1
        return self.jump_unread_result

    def _jump_to_next_stopped_agent(self) -> bool:
        self.jump_stopped_count += 1
        return self.jump_stopped_result

    def action_refresh_agents_full_history(self) -> None:
        self.full_history_refresh_count += 1

    def _toggle_all_unread_done_agents_read(self) -> _BulkUnreadToggleResult:
        self.mark_all_unread_count += 1
        return self.mark_all_unread_result

    def _start_prompt_history_from_last_selection(
        self,
        *,
        show_cancelled: bool = False,
        edit_first: bool = False,
    ) -> None:
        self.prompt_history_calls.append(
            {"show_cancelled": show_cancelled, "edit_first": edit_first}
        )

    def _show_prompt_input_bar_for_home(self) -> None:
        self.home_agent_count += 1

    def _start_agent_from_patch_quick(self) -> None:
        self.quick_patch_agent_count += 1

    def _start_agent_from_agent_quick(self) -> None:
        self.quick_selected_agent_count += 1

    def _start_agents_from_marked(self) -> None:
        self.marked_agent_run_count += 1

    def _kill_and_edit_agent(self) -> None:
        self.kill_and_edit_count += 1

    def _bulk_kill_marked_agents_and_edit(self) -> None:
        self.bulk_kill_and_edit_count += 1

    def _kill_and_edit_last_launch(self) -> None:
        self.kill_and_edit_last_count += 1

    def action_update_sase_shortcut(self) -> None:
        self.update_sase_shortcut_count += 1

    def action_jump_to_last_error(self) -> None:
        self.jump_to_last_error_count += 1

    def action_edit_query(self) -> None:
        self.edit_query_count += 1

    def action_show_help(self) -> None:
        self.show_help_count += 1

    async def action_open_prompt_stash(self) -> None:
        self.open_prompt_stash_count += 1


class _FakeEntryPoints(EntryPointsMixin):
    """Minimal app stand-in for direct entry-point actions."""

    def __init__(self) -> None:
        self.home_agent_count = 0

    def _show_prompt_input_bar_for_home(self) -> None:
        self.home_agent_count += 1


def _make_cs(name: str) -> MagicMock:
    cs = MagicMock()
    cs.name = name
    return cs


def _capture_bindings(
    footer: KeybindingFooter,
) -> list[tuple[list[tuple[str, str]], str | None]]:
    """Replace ``_update_display`` with a recorder for the bindings/mode args."""
    captured: list[tuple[list[tuple[str, str]], str | None]] = []
    footer._update_display = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda bindings, mode_label=None: captured.append(
            (list(bindings), mode_label)
        )
    )
    return captured


def _last_keys(captured: list[tuple[list[tuple[str, str]], str | None]]) -> set[str]:
    return {k for k, _ in captured[-1][0]}


def _last_labels(captured: list[tuple[list[tuple[str, str]], str | None]]) -> set[str]:
    return {label for _, label in captured[-1][0]}
