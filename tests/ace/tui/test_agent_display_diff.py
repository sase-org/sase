"""Display diff refresh paths for finalized Agents-tab lists."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
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
        merge_tag_panels: bool = False,
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
        self._agent_panels_grouped = merge_tag_panels
        self._panel_group = AgentPanelGroup.from_agents(
            self._agents,
            merge_tag_panels=merge_tag_panels,
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
    tag: str | None,
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
        tag=tag,
    )


def _display_costs(app: _DisplayDiffApp) -> list[str | None]:
    return [record.display_cost for record in app._agents_refresh_trace_records]


def test_same_position_row_change_patches_without_panel_rebuild(
    monkeypatch: Any,
) -> None:
    old_agent = _agent("alpha", tag="apple", suffix="a1", status="RUNNING")
    new_agent = replace(old_agent, status="DONE")
    app = _DisplayDiffApp([old_agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 1
    assert widget._agents[0].status == "DONE"
    assert app.full_rebuilds == 0
    assert "row_patch" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)
    assert app._agent_detail_debouncer.is_pending


def test_single_panel_addition_rebuilds_only_affected_panel(monkeypatch: Any) -> None:
    apple = _agent("apple-one", tag="apple", suffix="a1")
    banana = _agent("banana-one", tag="banana", suffix="b1")
    added = _agent("apple-two", tag="apple", suffix="a2")
    app = _DisplayDiffApp([apple, banana], monkeypatch)
    apple_widget = app._widgets["#agent-list-panel"]
    banana_widget = app._widgets["#agent-list-panel-1"]

    app._agents = [apple, added, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 2
    assert banana_widget.update_list_calls == 1
    assert [agent.identity for agent in apple_widget._agents] == [
        apple.identity,
        added.identity,
    ]
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_single_panel_removal_removes_then_rebuilds_affected_panel(
    monkeypatch: Any,
) -> None:
    apple_one = _agent("apple-one", tag="apple", suffix="a1")
    apple_two = _agent("apple-two", tag="apple", suffix="a2")
    banana = _agent("banana-one", tag="banana", suffix="b1")
    app = _DisplayDiffApp([apple_one, apple_two, banana], monkeypatch)
    apple_widget = app._widgets["#agent-list-panel"]
    banana_widget = app._widgets["#agent-list-panel-1"]

    app._agents = [apple_one, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple_one, apple_two, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 2
    assert banana_widget.update_list_calls == 1
    assert [agent.identity for agent in apple_widget._agents] == [apple_one.identity]
    assert app.full_rebuilds == 0
    assert "row_remove" in _display_costs(app)
    assert "display_panel_rebuild" in _display_costs(app)


def test_tag_move_between_existing_panels_rebuilds_source_and_target(
    monkeypatch: Any,
) -> None:
    apple_one = _agent("apple-one", tag="apple", suffix="a1")
    apple_two = _agent("apple-two", tag="apple", suffix="a2")
    banana = _agent("banana-one", tag="banana", suffix="b1")
    moved = replace(apple_one, tag="banana")
    app = _DisplayDiffApp([apple_one, apple_two, banana], monkeypatch)
    apple_widget = app._widgets["#agent-list-panel"]
    banana_widget = app._widgets["#agent-list-panel-1"]

    app._agents = [moved, apple_two, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple_one, apple_two, banana],
        defer_detail=True,
    )

    assert apple_widget.update_list_calls == 2
    assert banana_widget.update_list_calls == 2
    assert [agent.identity for agent in apple_widget._agents] == [apple_two.identity]
    assert [agent.identity for agent in banana_widget._agents] == [
        moved.identity,
        banana.identity,
    ]
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "display_full_rebuild" not in _display_costs(app)


def test_merged_panel_tag_label_change_rebuilds_panel(monkeypatch: Any) -> None:
    old_agent = _agent("alpha", tag="apple", suffix="a1")
    new_agent = replace(old_agent, tag="banana")
    app = _DisplayDiffApp([old_agent], monkeypatch, merge_tag_panels=True)
    widget = app._widgets["#agent-list-panel"]

    app._agents = [new_agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[old_agent],
        defer_detail=True,
    )

    assert widget.update_list_calls == 2
    assert widget._agents[0].tag == "banana"
    assert app.full_rebuilds == 0
    assert "display_panel_rebuild" in _display_costs(app)
    assert "row_patch" not in _display_costs(app)


def test_panel_collection_change_falls_back_to_full_rebuild(monkeypatch: Any) -> None:
    apple = _agent("apple-one", tag="apple", suffix="a1")
    banana = _agent("banana-one", tag="banana", suffix="b1")
    app = _DisplayDiffApp([apple], monkeypatch)

    app._agents = [apple, banana]
    app._refresh_agents_display_after_finalize(
        previous_agents=[apple],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert app._agents_refresh_trace_records[0].fallback_reason == (
        "panel_membership_change"
    )
    assert "display_full_rebuild" in _display_costs(app)


def test_same_list_falls_back_when_previous_rows_were_not_rendered(
    monkeypatch: Any,
) -> None:
    agent = _agent("alpha", tag=None, suffix="a1")
    app = _DisplayDiffApp([agent], monkeypatch)
    widget = app._widgets["#agent-list-panel"]
    widget.clear_options()

    app._agents = [agent]
    app._refresh_agents_display_after_finalize(
        previous_agents=[agent],
        defer_detail=True,
    )

    assert app.full_rebuilds == 1
    assert "display_full_rebuild" in _display_costs(app)
