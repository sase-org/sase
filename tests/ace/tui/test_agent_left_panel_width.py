"""Width clamps for the Agents-tab left panel."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.app import _MAX_AGENT_LIST_WIDTH, _MIN_AGENT_LIST_WIDTH
from sase.ace.tui.widgets.agent_list import AgentList


class _Styles:
    def __init__(self) -> None:
        self.width: int | None = None


class _Container:
    def __init__(self) -> None:
        self.styles = _Styles()


class _QueryResults:
    def __init__(self, widgets: list[object]) -> None:
        self._widgets = widgets

    def results(self, _type: type[AgentList]) -> list[object]:
        return self._widgets


class _FakeApp(EventHandlersMixin):
    def __init__(self, widgets: list[object] | None = None) -> None:
        self.container = _Container()
        self.widgets = widgets or []

    def query_one(self, selector: str, _type: Any = None) -> _Container:
        assert selector == "#agent-list-container"
        return self.container

    def query(self, selector: str) -> _QueryResults:
        assert selector == "#agent-list-container AgentList"
        return _QueryResults(self.widgets)


class _FakeAgentList:
    def __init__(self, requested_width: int) -> None:
        self._requested_width = requested_width


def test_agent_left_panel_width_clamps_to_raised_max() -> None:
    app = _FakeApp()

    app.on_agent_list_width_changed(AgentList.WidthChanged(_MAX_AGENT_LIST_WIDTH + 50))

    assert app.container.styles.width == _MAX_AGENT_LIST_WIDTH


def test_agent_left_panel_width_uses_widest_mounted_panel_request() -> None:
    app = _FakeApp(
        [
            _FakeAgentList(_MIN_AGENT_LIST_WIDTH),
            _FakeAgentList(104),
            _FakeAgentList(72),
        ]
    )

    app.on_agent_list_width_changed(AgentList.WidthChanged(_MIN_AGENT_LIST_WIDTH))

    assert app.container.styles.width == 104


def test_agent_left_panel_width_clamps_aggregated_panel_request() -> None:
    app = _FakeApp(
        [
            _FakeAgentList(_MAX_AGENT_LIST_WIDTH + 25),
            _FakeAgentList(_MIN_AGENT_LIST_WIDTH),
        ]
    )

    app.on_agent_list_width_changed(AgentList.WidthChanged(_MIN_AGENT_LIST_WIDTH))

    assert app.container.styles.width == _MAX_AGENT_LIST_WIDTH
