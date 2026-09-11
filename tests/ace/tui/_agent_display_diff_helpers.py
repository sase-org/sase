"""Shared harness for Agents-tab display diff tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_diff import (
    build_agent_display_diff,
    diff_touches_workflow_tree,
)
from sase.ace.tui.actions.agents._refresh_trace import _AgentRefreshTraceRecord
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.util.debounce import DetailPanelDebouncer
from sase.ace.tui.widgets.agent_list import AgentList


@dataclass
class _Timer:
    stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class _Size:
    def __init__(self, height: int) -> None:
        self.height = height


class _Container:
    def __init__(self, children: list[AgentList]) -> None:
        self.children = list(children)
        self.size = _Size(40)

    def mount(self, widget: AgentList) -> None:
        self.children.append(widget)


class _QueryResult:
    def __init__(self, items: list[AgentList]) -> None:
        self._items = items

    def results(self, _type: Any = None) -> Any:
        return iter(self._items)


class _DetailWidget:
    pass


class _FooterWidget:
    pass


class _DisplayDiffApp(AgentDisplayMixin):
    def __init__(
        self,
        agents: list[Agent],
        monkeypatch: Any,
        *,
        merge_tribe_panels: bool = False,
        collapsed_panel_keys: set[str | None] | None = None,
    ) -> None:
        self._agents = list(agents)
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._agent_detail_debouncer = DetailPanelDebouncer(self)  # type: ignore[arg-type]
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents = set()
        self._unread_completed_agent_ids = set()
        self._manual_unread_agent_ids = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint = {}
        self._entry_jump_banner_to_hint = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key = None
        self._agent_panels_grouped = merge_tribe_panels
        self._collapsed_panel_keys = set(collapsed_panel_keys or ())
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            merge_tribe_panels=merge_tribe_panels,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._agents_first_load_done = True
        self._agents_refresh_active_source = "delta"
        self._agents_refresh_trace_records: list[_AgentRefreshTraceRecord] = []
        self._pending_callback: Any = None
        self.info_updates = 0
        self.detail_updates = 0
        self.full_rebuilds = 0

        self._widgets: dict[str, Any] = {
            "#agent-detail-panel": _DetailWidget(),
            "#keybinding-footer": _FooterWidget(),
        }
        panel_widgets: list[AgentList] = []
        from sase.ace.tui.actions.agents._display import _panel_widget_id

        for idx, _key in enumerate(self._panel_group.panel_keys):
            wid = _panel_widget_id(idx)
            widget = AgentList(id=wid)
            widget.update_list_calls = 0  # type: ignore[attr-defined]
            original_update_list = widget.update_list

            def counted_update_list(
                *args: Any,
                _original: Any = original_update_list,
                _widget: AgentList = widget,
                **kwargs: Any,
            ) -> None:
                _widget.update_list_calls += 1  # type: ignore[attr-defined]
                _original(*args, **kwargs)

            monkeypatch.setattr(widget, "update_list", counted_update_list)
            monkeypatch.setattr(widget, "post_message", lambda _msg: None)
            panel_widgets.append(widget)
            self._widgets[f"#{wid}"] = widget
        self._container = _Container(panel_widgets)
        self._widgets["#agent-list-container"] = self._container

        self._refresh_panel_widgets(jump_hints=None)

    def query_one(self, selector: str, _type: Any = None) -> Any:
        del _type
        return self._widgets[selector]

    def query(self, _selector: str) -> _QueryResult:
        return _QueryResult(self._container.children)

    def set_timer(self, _delay: float, callback: Any) -> _Timer:
        self._pending_callback = callback
        return _Timer()

    def _prune_stale_marked_agents(self) -> None:
        visible = {agent.identity for agent in self._agents}
        self._marked_agents.intersection_update(visible)

    def _update_agents_info_panel(self) -> None:
        self.info_updates += 1

    def _apply_agent_detail_update(self, _detail: Any, _footer: Any) -> None:
        self.detail_updates += 1

    def _refresh_agents_display_impl(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail
        self.full_rebuilds += 1


def _agent(
    name: str,
    *,
    tribe: str | None,
    suffix: str,
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/repo/project/project.sase",
        status=status,
        start_time=datetime(2026, 6, 8, 12, 0, 0),
        agent_name=name,
        raw_suffix=suffix,
        tribe=tribe,
    )


def _workflow_agent(
    name: str,
    *,
    suffix: str,
    status: str = "RUNNING",
    agent_type: AgentType = AgentType.WORKFLOW,
    activity: str | None = None,
    step_output: dict[str, Any] | None = None,
    hidden: bool = False,
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/repo/project/project.sase",
        status=status,
        start_time=datetime(2026, 6, 8, 12, 0, 0),
        raw_suffix=suffix,
        workflow=name if agent_type is AgentType.WORKFLOW else None,
        activity=activity,
        step_output=step_output,
        hidden=hidden,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
    )


def _display_costs(app: _DisplayDiffApp) -> list[str | None]:
    return [record.display_cost for record in app._agents_refresh_trace_records]


def _touches_workflow_tree(
    previous_agents: list[Agent],
    next_agents: list[Agent],
) -> bool:
    diff = build_agent_display_diff(previous_agents, next_agents)
    return diff_touches_workflow_tree(diff, previous_agents, next_agents)
