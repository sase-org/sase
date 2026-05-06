"""Per-panel border-title labels for vertically stacked Agents-tab panels.

Each ``AgentList`` panel must show a ``border_title`` identifying its tag
(``(untagged)`` / ``@<tag>``) plus a ``· N`` agent count, refreshed every
time :meth:`AgentDisplayMixin._refresh_panel_widgets` runs (panel widget
ids correspond to index slots, not fixed tags — alphabetic shifts can
flip which tag a slot points at).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _ListWidget:
    def __init__(self, wid: str) -> None:
        self.id = wid
        self.border_title: Text | str | None = None
        self.highlighted: int | None = None
        self._classes: set[str] = set()

    def update_list(self, *args: Any, **kwargs: Any) -> None:
        return

    def update_highlight(self, *args: Any, **kwargs: Any) -> None:
        return

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def focus(self) -> None:
        return


class _Container:
    def __init__(self, children: list[_ListWidget]) -> None:
        self.children = list(children)

    def mount(self, widget: _ListWidget) -> None:
        self.children.append(widget)


class _FakeApp(AgentDisplayMixin):
    def __init__(self, agents: list[Agent]) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._detail_update_timer = None
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._panel_group = AgentPanelGroup.from_agents(agents)

        from sase.ace.tui.actions.agents._display import _panel_widget_id

        self._panel_widgets: dict[str, _ListWidget] = {}
        for idx in range(len(self._panel_group.panel_keys)):
            wid = _panel_widget_id(idx)
            self._panel_widgets[wid] = _ListWidget(wid)
        self._container = _Container(list(self._panel_widgets.values()))

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-list-container":
            return self._container
        wid = selector.lstrip("#")
        return self._panel_widgets[wid]

    def _focus_focused_panel_widget(self) -> None:
        return


def _agent(*, name: str, tag: str | None = None, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.gp",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=suffix,
    )


def _title_text(widget: _ListWidget) -> Text:
    title = widget.border_title
    assert isinstance(title, Text)
    return title


def _assert_title_span(
    title: Text, *, start: int, end: int, style: str, text: str
) -> None:
    assert title.plain[start:end] == text
    assert any(
        span.start == start and span.end == end and span.style == style
        for span in title.spans
    )


def test_panel_titles_label_untagged_and_tags_with_counts() -> None:
    agents = [
        _agent(name="u1", suffix="t1"),
        _agent(name="u2", suffix="t2"),
        _agent(name="b1", tag="banana", suffix="t3"),
        _agent(name="a1", tag="apple", suffix="t4"),
        _agent(name="a2", tag="apple", suffix="t5"),
    ]
    app = _FakeApp(agents)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    main_title = _title_text(main)
    assert main_title.plain == "(untagged) · 2"
    _assert_title_span(
        main_title, start=0, end=10, style="dim #AFAFAF", text="(untagged)"
    )

    # Tag panels follow in alphabetical order: apple (idx 1), banana (idx 2).
    apple = app._panel_widgets["agent-list-panel-1"]
    banana = app._panel_widgets["agent-list-panel-2"]
    apple_title = _title_text(apple)
    banana_title = _title_text(banana)
    assert apple_title.plain == "@apple · 2"
    assert banana_title.plain == "@banana · 1"
    _assert_title_span(apple_title, start=0, end=6, style="bold #FFD75F", text="@apple")
    _assert_title_span(apple_title, start=6, end=10, style="#AFAFAF", text=" · 2")
    _assert_title_span(
        banana_title, start=0, end=7, style="bold #FFD75F", text="@banana"
    )


def test_panel_titles_track_alphabetical_slot_order() -> None:
    """Slot identity is by index, not tag — titles follow alphabetic order
    of the current tag set, not insertion order of the agents.
    """
    agents = [
        _agent(name="z1", tag="zulu", suffix="t1"),
        _agent(name="a1", tag="alpha", suffix="t2"),
        _agent(name="m1", tag="mike", suffix="t3"),
    ]
    app = _FakeApp(agents)
    app._refresh_panel_widgets(jump_hints=None)

    assert app._panel_group.panel_keys == ["alpha", "mike", "zulu"]
    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == "@alpha · 1"
    assert _title_text(app._panel_widgets["agent-list-panel-1"]).plain == "@mike · 1"
    assert _title_text(app._panel_widgets["agent-list-panel-2"]).plain == "@zulu · 1"
    assert "agent-list-panel-3" not in app._panel_widgets
