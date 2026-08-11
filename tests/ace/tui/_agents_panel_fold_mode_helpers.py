"""Shared harness for Agents-tab fold-mode tests."""

from types import SimpleNamespace

from sase.ace.tui.actions.navigation._fold import FoldNavigationMixin
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.fold_state import FoldLevel, SectionFoldStateManager


class _FoldApp(FoldNavigationMixin):
    def __init__(
        self,
        *,
        tab: str = "agents",
        clan: bool = True,
        family: bool = False,
        panel_focused: bool = False,
        has_agent: bool = True,
        neighbor_count: int = 0,
        foldable_bead_rows: bool = False,
        slow_tool_call_count: int = 0,
    ) -> None:
        self.current_tab = tab
        self.current_artifacts_subtab = "patches"
        self._fold_mode_active = False
        self._keymap_registry = load_keymap_registry({})
        self.panel_fold_level = FoldLevel.COLLAPSED
        self._panel_fold_overrides = SectionFoldStateManager()
        self.commits_collapsed = FoldLevel.COLLAPSED
        self.hooks_collapsed = FoldLevel.COLLAPSED
        self.mentors_collapsed = FoldLevel.COLLAPSED
        self.timestamps_collapsed = FoldLevel.COLLAPSED
        self.deltas_collapsed = FoldLevel.COLLAPSED
        self.section_id: str | None = "errors"
        self.selected_agent = (
            SimpleNamespace(
                is_clan_container=clan,
                is_family_container_row=family,
                is_family_root_entry=family,
                is_workflow_child=False,
                is_hidden_step=False,
                is_family_member_child=False,
                presented_agent_name="fold-test",
                presented_identity_name="fold-test",
            )
            if has_agent
            else None
        )
        self.refresh_count = 0
        self.notifications: list[str] = []
        self.panel_focused = panel_focused
        self.neighbor_count = neighbor_count
        self.foldable_bead_rows = foldable_bead_rows
        self.slow_tool_call_count = slow_tool_call_count

    def _refresh_current_tab(self) -> None:
        self.refresh_count += 1

    def _current_agent_metadata_section_id(self) -> str | None:
        return self.section_id

    def _get_selected_agent(self) -> object | None:
        return self.selected_agent

    def _selected_agent_neighbor_count(self, _agent: object) -> int:
        return self.neighbor_count

    def _selected_lane_has_foldable_bead_rows(self, _agent: object) -> bool:
        return self.foldable_bead_rows

    def _selected_agent_slow_tool_call_count(self, _agent: object) -> int:
        return self.slow_tool_call_count

    def _resolve_focused_collapsed_panel(self) -> object | None:
        return object() if self.panel_focused else None

    def notify(self, message: str) -> None:
        self.notifications.append(message)


def _press(app: _FoldApp, key: str) -> None:
    app._fold_mode_active = True
    assert app._handle_fold_key(key) is True
    assert app._fold_mode_active is False
