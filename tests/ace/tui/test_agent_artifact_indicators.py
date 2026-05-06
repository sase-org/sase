"""Agent-tab artifact indicator panel integration tests."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._display import AgentDisplayMixin, _panel_widget_id
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.artifact_indicator import render_artifact_indicator
from sase.ace.tui.models.artifact_summary_cache import ArtifactSummaryCache
from sase.core.artifact_wire import ArtifactSummaryWire, ArtifactTypeCountWire


class _CapturingAgentList:
    def __init__(self, id: str | None = None) -> None:
        self.id = id
        self.border_title: str | None = None
        self.update_list_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.update_highlight_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self._classes: set[str] = set()
        self.option_count = 0

    def update_list(self, *args: Any, **kwargs: Any) -> None:
        self.update_list_calls.append((args, kwargs))
        self.option_count = len(args[0]) if args else 0

    def update_highlight(self, *args: Any, **kwargs: Any) -> None:
        self.update_highlight_calls.append((args, kwargs))

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return

    def remove(self) -> None:
        return


class _Container:
    def __init__(self, children: list[_CapturingAgentList]) -> None:
        self.children = list(children)
        self.size = type("Size", (), {"height": 0})()

    def mount(self, widget: _CapturingAgentList) -> None:
        self.children.append(widget)


class _FakeApp(AgentDisplayMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_banner_to_hint: dict[
            tuple[Any, int, tuple[str, ...]], str
        ] = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._grouping_mode = GroupingMode.STANDARD
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(agents)
        self._agent_panel_index_cache = None
        self._panel_keys_cache = None
        self._nav_stops_cache = None
        self._artifact_summary_cache = ArtifactSummaryCache()

        self._panel_widgets: dict[str, _CapturingAgentList] = {}
        for idx in range(len(self._panel_group.panel_keys)):
            wid = _panel_widget_id(idx)
            self._panel_widgets[wid] = _CapturingAgentList(wid)
        self._container = _Container(list(self._panel_widgets.values()))

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-list-container":
            return self._container
        wid = selector.lstrip("#")
        return self._panel_widgets[wid]

    def query(self, _selector: str) -> Any:
        class _Results:
            def __init__(self, widgets: list[_CapturingAgentList]) -> None:
                self._widgets = widgets

            def results(self, _type: Any) -> list[_CapturingAgentList]:
                return self._widgets

        return _Results(list(self._panel_widgets.values()))

    def _focus_focused_panel_widget(self) -> None:
        return

    def _update_agents_info_panel(self) -> None:
        return


def _agent(
    *,
    name: str,
    suffix: str,
    tag: str | None = None,
    artifacts_dir: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/home/me/.sase/projects/demo/demo.gp",
        status="RUNNING",
        start_time=datetime(2026, 5, 6, 12, 0, 0),
        agent_name=name,
        raw_suffix=suffix,
        tag=tag,
        artifacts_dir=artifacts_dir,
    )


def _summary(
    artifact_id: str,
    artifact_type: str,
) -> ArtifactSummaryWire:
    return ArtifactSummaryWire(
        artifact_id=artifact_id,
        state="ok",
        total_linked_count=1,
        file_type_counts=[
            ArtifactTypeCountWire(artifact_type=artifact_type, total_count=1),
        ],
    )


def test_tag_panel_refresh_threads_local_artifact_indicators(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("sase.ace.tui.widgets.AgentList", _CapturingAgentList)
    agents = [
        _agent(name="plain-agent", suffix="1"),
        _agent(name="tagged-agent", suffix="2", tag="feature"),
    ]
    app = _FakeApp(agents)
    app._artifact_summary_cache.update(
        [
            _summary("plain-agent", "plan"),
            _summary("tagged-agent", "diff"),
        ]
    )

    app._refresh_panel_widgets(jump_hints=None)

    main_kwargs = app._panel_widgets["agent-list-panel"].update_list_calls[-1][1]
    tag_kwargs = app._panel_widgets["agent-list-panel-1"].update_list_calls[-1][1]
    main_indicator = main_kwargs["artifact_indicators"][0]
    tag_indicator = tag_kwargs["artifact_indicators"][0]

    assert render_artifact_indicator(main_indicator).plain == "art 1 plan1"
    assert render_artifact_indicator(tag_indicator).plain == "art 1 diff1"


def test_agent_highlight_refresh_does_not_reload_summaries_or_rebuild_panels(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr("sase.ace.tui.widgets.AgentList", _CapturingAgentList)
    summary = MagicMock(return_value=[])
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifact_summaries.artifact_facade.artifact_summary",
        summary,
    )
    app = _FakeApp(
        [
            _agent(name="plain-agent", suffix="1"),
            _agent(name="other-agent", suffix="2"),
        ]
    )
    app._artifact_summary_cache.update([_summary("plain-agent", "plan")])
    app._refresh_panel_widgets(jump_hints=None)
    widget = app._panel_widgets["agent-list-panel"]
    widget.update_list_calls.clear()

    app.current_idx = 1
    app._refresh_panel_highlights()

    summary.assert_not_called()
    assert widget.update_list_calls == []
    assert widget.update_highlight_calls[-1][0][0] == 1
