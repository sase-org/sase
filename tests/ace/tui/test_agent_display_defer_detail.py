"""Tests for deferred detail rendering on full agents list refresh."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _ListWidget:
    def __init__(self) -> None:
        self.highlighted = None

    def update_list(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def update_highlight(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return


class _DetailWidget:
    def update_display(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def show_empty(self) -> None:
        return

    def is_file_visible(self) -> bool:
        return False


class _FooterWidget:
    def update_agent_bindings(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return


class _FakeApp(AgentDisplayMixin):
    def __init__(self) -> None:
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="test",
            project_file="/tmp/test.gp",
            status="RUNNING",
            start_time=None,
            workflow="crs",
        )
        self._agents = [agent]
        self._fold_counts = {}
        self._agent_search_query = ""
        self._detail_update_timer = None
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._pinned_panel_focused = "main"
        self._main_panel_indices = [0]
        self._pinned_panel_indices = []
        self._main_panel_idx_map = {0: 0}
        self._pinned_panel_idx_map = {}
        self._non_child_main_indices = [0]
        self._pinned_agents = set()
        self._marked_agents = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._countdown_remaining = 0
        self._pending_callback = None
        self._widgets = {
            "#agent-list-panel": _ListWidget(),
            "#pinned-list-panel": _ListWidget(),
            "#agent-detail-panel": _DetailWidget(),
            "#keybinding-footer": _FooterWidget(),
        }
        self.detail_calls = 0

    def query_one(self, selector: str, _type=None):  # type: ignore[no-untyped-def]
        return self._widgets[selector]

    def set_timer(self, _delay: float, callback):  # type: ignore[no-untyped-def]
        self._pending_callback = callback
        return _Timer()

    def _prune_stale_marked_agents(self) -> None:
        return

    def _update_panel_focus_styling(self) -> None:
        return

    def _update_agents_info_panel(self) -> None:
        return

    def _get_selected_agent(self):  # type: ignore[no-untyped-def]
        return self._agents[0]

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return "test"

    def _apply_agent_detail_update(self, agent_detail, footer_widget) -> None:  # type: ignore[no-untyped-def]
        del agent_detail, footer_widget
        self.detail_calls += 1


def test_refresh_list_with_defer_detail_schedules_timer() -> None:
    app = _FakeApp()

    app._refresh_agents_display(list_changed=True, defer_detail=True)

    assert app.detail_calls == 0
    assert app._detail_update_timer is not None
    assert app._pending_callback is not None


def test_refresh_list_without_defer_updates_detail_immediately() -> None:
    app = _FakeApp()

    app._refresh_agents_display(list_changed=True, defer_detail=False)

    assert app.detail_calls == 1
    assert app._pending_callback is None
