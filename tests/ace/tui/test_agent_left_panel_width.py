"""Width clamps for the Agents-tab left panel."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.app import _MAX_AGENT_LIST_WIDTH
from sase.ace.tui.widgets.agent_list import AgentList


class _Styles:
    def __init__(self) -> None:
        self.width: int | None = None


class _Container:
    def __init__(self) -> None:
        self.styles = _Styles()


class _FakeApp(EventHandlersMixin):
    def __init__(self) -> None:
        self.container = _Container()

    def query_one(self, selector: str, _type: Any = None) -> _Container:
        assert selector == "#agent-list-container"
        return self.container


def test_agent_left_panel_width_clamps_to_raised_max() -> None:
    app = _FakeApp()

    app.on_agent_list_width_changed(AgentList.WidthChanged(_MAX_AGENT_LIST_WIDTH + 50))

    assert app.container.styles.width == _MAX_AGENT_LIST_WIDTH
