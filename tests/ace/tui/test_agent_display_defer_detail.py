"""Tests for deferred detail rendering on full agents list refresh."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.util.debounce import DetailPanelDebouncer


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _ListWidget:
    def __init__(self, wid: str = "agent-list-panel") -> None:
        self.highlighted = None
        self.id = wid
        self._classes: set[str] = set()

    def update_list(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def update_highlight(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return


class _DetailWidget:
    tools_detail_level = 0

    def update_display(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        return

    def show_empty(self) -> None:
        return

    def is_file_visible(self) -> bool:
        return False

    def is_tools_visible(self) -> bool:
        return False


class _FooterWidget:
    def __init__(self) -> None:
        self.leader_binding_calls: list[dict[str, object]] = []
        self.agent_binding_calls: list[dict[str, object]] = []

    def update_agent_bindings(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.agent_binding_calls.append(dict(kwargs))

    def update_leader_bindings(self, **kwargs: object) -> None:
        self.leader_binding_calls.append(dict(kwargs))


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)

    def mount(self, widget: _ListWidget) -> None:
        self.children.append(widget)

    def remove(self) -> None:
        return


class _QueryResult:
    def __init__(self, items: list[_ListWidget]) -> None:
        self._items = items

    def results(self, _type=None):  # type: ignore[no-untyped-def]
        return iter(self._items)


class _FakeApp(AgentDisplayMixin):
    def __init__(self) -> None:
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name="test",
            project_file="/tmp/test.sase",
            status="RUNNING",
            start_time=None,
            workflow="crs",
        )
        self._agents = [agent]
        self._fold_counts = {}
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._countdown_remaining = 0
        from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
        from sase.ace.tui.models.agent_panels import AgentPanelGroup

        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(self._agents)
        self._pending_callback = None
        self.unread_completed_available = False
        self.stopped_available = False

        list_widget = _ListWidget()
        footer_widget = _FooterWidget()
        self._container = _Container([list_widget])
        self._widgets = {
            "#agent-list-panel": list_widget,
            "#agent-list-container": self._container,
            "#agent-detail-panel": _DetailWidget(),
            "#keybinding-footer": footer_widget,
        }
        self.detail_calls = 0
        self.footer_widget = footer_widget

    def query_one(self, selector: str, _type=None):  # type: ignore[no-untyped-def]
        return self._widgets[selector]

    def query(self, selector: str):  # type: ignore[no-untyped-def]
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback):  # type: ignore[no-untyped-def]
        self._pending_callback = callback
        return _Timer()

    def _prune_stale_marked_agents(self) -> None:
        return

    def _update_agents_info_panel(self) -> None:
        return

    def _get_selected_agent(self):  # type: ignore[no-untyped-def]
        return self._agents[0]

    def _resolve_agent_cl_name(self, _agent: Agent) -> str | None:
        return "test"

    def _has_unread_completed_agent(self) -> bool:
        return self.unread_completed_available

    def _has_stopped_agent(self) -> bool:
        return self.stopped_available

    def _apply_agent_detail_update(self, agent_detail, footer_widget) -> None:  # type: ignore[no-untyped-def]
        del agent_detail, footer_widget
        self.detail_calls += 1


def test_refresh_list_with_defer_detail_schedules_timer() -> None:
    app = _FakeApp()

    app._refresh_agents_display(list_changed=True, defer_detail=True)

    assert app.detail_calls == 0
    assert app._agent_detail_debouncer.is_pending
    assert app._pending_callback is not None


def test_refresh_list_without_defer_updates_detail_immediately() -> None:
    app = _FakeApp()

    app._refresh_agents_display(list_changed=True, defer_detail=False)

    assert app.detail_calls == 1
    assert app._pending_callback is None


def test_leader_footer_refresh_preserves_plan_notification_binding() -> None:
    app = _FakeApp()
    app._leader_mode_active = True
    app._agents[0].status = "PLAN"

    app._apply_agent_footer_update(
        _DetailWidget(), app.footer_widget, app._get_selected_agent()
    )

    assert app.footer_widget.leader_binding_calls[-1]["current_tab"] == "agents"
    assert app.footer_widget.leader_binding_calls[-1]["has_notification"] is True


def test_leader_footer_refresh_clears_non_notification_binding() -> None:
    app = _FakeApp()
    app._leader_mode_active = True
    app._agents[0].status = "RUNNING"

    app._apply_agent_footer_update(
        _DetailWidget(), app.footer_widget, app._get_selected_agent()
    )

    assert app.footer_widget.leader_binding_calls[-1]["has_notification"] is False


def test_leader_footer_refresh_keeps_unread_and_stopped_flags() -> None:
    app = _FakeApp()
    app._leader_mode_active = True
    app.unread_completed_available = True
    app.stopped_available = True

    app._apply_agent_footer_update(
        _DetailWidget(), app.footer_widget, app._get_selected_agent()
    )

    call = app.footer_widget.leader_binding_calls[-1]
    assert call["has_unread_completed_agent"] is True
    assert call["has_stopped_agent"] is True


def test_footer_refresh_uses_parent_jump_resolver_capability() -> None:
    app = _FakeApp()
    app._resolve_agent_parent_jump_target = lambda: SimpleNamespace(kind="family")  # type: ignore[attr-defined]

    app._apply_agent_footer_update(
        _DetailWidget(), app.footer_widget, app._get_selected_agent()
    )

    assert app.footer_widget.agent_binding_calls[-1]["parent_jump_kind"] == "family"
