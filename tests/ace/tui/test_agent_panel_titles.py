"""Per-panel border-title labels for vertically stacked Agents-tab panels.

Each ``AgentList`` panel must show a ``border_title`` identifying its tribe
(``(no tribe)`` / ``#<tribe>``) plus a ``· N`` agent count, refreshed every
time :meth:`AgentDisplayMixin._refresh_panel_widgets` runs (panel widget
ids correspond to index slots, not fixed tribes — alphabetic shifts can
flip which tribe a slot points at).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.text import Text

from sase.ace.tui.actions.agents._display import AgentDisplayMixin
from sase.ace.tui.actions.agents._display_panel_titles import (
    _PANEL_ISOLATION_RESTORE_STYLE,
    AgentPanelCounts,
    agent_panel_border_title,
)
from sase.ace.tui.actions.agents._display_panels import (
    _PANEL_COUNT_STYLE,
    _PANEL_METRIC_STYLES,
)
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
    def __init__(
        self, agents: list[Agent], *, merge_tribe_panels: bool = False
    ) -> None:
        self._agents = agents
        self._fold_counts: dict[str, tuple[int, int]] = {}
        self._agent_search_query = ""
        self._detail_update_timer = None
        self.current_idx = 0
        self.current_attempt_number = None
        self.refresh_interval = 10
        self.current_tab = "agents"
        self._marked_agents: set[Any] = set()
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._entry_jump_mode_active = False
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._countdown_remaining = 0
        self._group_fold_registry = AgentGroupFoldRegistry()
        self._current_group_key = None
        self._agent_panels_grouped = merge_tribe_panels
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            merge_tribe_panels=merge_tribe_panels,
        )

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


def _agent(
    *,
    name: str,
    tribe: str | None = None,
    suffix: str,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    agent_family_parallel: bool = False,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        agent_family_parallel=agent_family_parallel,
    )


def _title_text(widget: _ListWidget) -> Text:
    title = widget.border_title
    assert isinstance(title, Text)
    return title


def test_collapsed_panel_title_prepends_chevron_and_preserves_summary() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
    )

    assert title.plain == "▸ @chop · 3 [R1 W2]"


def test_selected_expanded_panel_title_has_focus_marker() -> None:
    title = agent_panel_border_title(
        "chop",
        21,
        counts=AgentPanelCounts(
            asking=1,
            running=2,
            waiting=3,
            failed=4,
            unread=5,
            read=6,
        ),
        selected=True,
    )

    assert title.plain == "❖ @chop · 21 [S1 R2 W3 F4 U5 D6]"
    selected_style = "#FFD75F"
    total_start = title.plain.index("21")
    _assert_title_span(
        title,
        start=total_start,
        end=total_start + 2,
        style=selected_style,
        text="21",
    )

    for character in "[]SRWFUD":
        position = title.plain.index(character, total_start + 2)
        _assert_title_range_style(
            title,
            start=position,
            end=position + 1,
            style=selected_style,
        )

    for token, metric_name in (
        ("S1", "asking"),
        ("R2", "running"),
        ("W3", "waiting"),
        ("F4", "failed"),
        ("U5", "unread"),
        ("D6", "read"),
    ):
        digit_position = title.plain.index(token, total_start + 2) + 1
        _assert_title_range_style(
            title,
            start=digit_position,
            end=digit_position + 1,
            style=_PANEL_METRIC_STYLES[metric_name],
        )

    separator_start = title.plain.index(" · ")
    _assert_title_span(
        title,
        start=separator_start,
        end=separator_start + 3,
        style=_PANEL_COUNT_STYLE,
        text=" · ",
    )


def test_panel_title_places_isolation_restore_marker_after_tribe_name() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        selected=True,
        isolation_restore_marked=True,
    )

    assert title.plain == "❖ @chop ↺ · 3 [R1 W2]"
    marker_start = title.plain.index("↺")
    _assert_title_span(
        title,
        start=marker_start,
        end=marker_start + 1,
        style=_PANEL_ISOLATION_RESTORE_STYLE,
        text="↺",
    )


def test_collapsed_panel_title_prepends_yellow_jump_hint() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
        jump_hint="x",
    )

    assert title.plain == "[x] ▸ @chop · 3 [R1 W2]"
    _assert_title_span(
        title,
        start=0,
        end=4,
        style="bold #FFFF00",
        text="[x] ",
    )


def test_panel_title_renders_two_character_jump_hint() -> None:
    title = agent_panel_border_title(
        "chop",
        3,
        counts=AgentPanelCounts(running=1, waiting=2),
        collapsed=True,
        jump_hint="0Z",
    )

    assert title.plain == "[0Z] ▸ @chop · 3 [R1 W2]"
    _assert_title_span(
        title,
        start=0,
        end=5,
        style="bold #FFFF00",
        text="[0Z] ",
    )


def test_panel_title_renders_multi_digit_numeric_selection_hint() -> None:
    title = agent_panel_border_title(
        None,
        2,
        counts=AgentPanelCounts(running=2),
        selection_hint=12,
    )

    assert title.plain == "[12] (no tribe) · 2 [R2]"
    _assert_title_span(
        title,
        start=0,
        end=5,
        style="bold #FFFF00",
        text="[12] ",
    )


def _assert_title_span(
    title: Text, *, start: int, end: int, style: str, text: str
) -> None:
    assert title.plain[start:end] == text
    assert any(
        span.start == start and span.end == end and span.style == style
        for span in title.spans
    )


def _assert_title_range_style(title: Text, *, start: int, end: int, style: str) -> None:
    assert title.plain[start:end]
    for position in range(start, end):
        resolved_style = next(
            (
                str(span.style)
                for span in reversed(title.spans)
                if span.start <= position < span.end
            ),
            str(title.style) if title.style else None,
        )
        assert resolved_style == style, (
            f"expected {title.plain[position]!r} at {position} to use {style}; "
            f"got {resolved_style}"
        )


def _assert_title_metric_styles(
    title: Text,
    *,
    neutral_ranges: list[tuple[int, int]],
    metric_digits: list[tuple[int, str]],
) -> None:
    for start, end in neutral_ranges:
        _assert_title_range_style(title, start=start, end=end, style=_PANEL_COUNT_STYLE)
    for position, metric_name in metric_digits:
        _assert_title_range_style(
            title,
            start=position,
            end=position + 1,
            style=_PANEL_METRIC_STYLES[metric_name],
        )


def test_panel_titles_label_no_tribe_and_tribes_with_counts() -> None:
    agents = [
        _agent(name="u1", suffix="t1"),
        _agent(name="u2", suffix="t2"),
        _agent(name="b1", tribe="banana", suffix="t3"),
        _agent(name="a1", tribe="apple", suffix="t4"),
        _agent(name="a2", tribe="apple", suffix="t5"),
    ]
    app = _FakeApp(agents)

    app._refresh_panel_widgets(jump_hints=None)

    main = app._panel_widgets["agent-list-panel"]
    main_title = _title_text(main)
    assert main_title.plain == "(no tribe) · 2 [R2]"
    _assert_title_span(
        main_title, start=0, end=10, style="dim #AFAFAF", text="(no tribe)"
    )

    # Tribe panels follow in alphabetical order: apple (idx 1), banana (idx 2).
    apple = app._panel_widgets["agent-list-panel-1"]
    banana = app._panel_widgets["agent-list-panel-2"]
    apple_title = _title_text(apple)
    banana_title = _title_text(banana)
    assert apple_title.plain == "@apple · 2 [R2]"
    assert banana_title.plain == "@banana · 1 [R1]"
    _assert_title_span(apple_title, start=0, end=6, style="bold #FFD75F", text="@apple")
    _assert_title_span(apple_title, start=6, end=9, style="#AFAFAF", text=" · ")
    _assert_title_span(apple_title, start=9, end=10, style="#AFAFAF", text="2")
    _assert_title_span(
        banana_title, start=0, end=7, style="bold #FFD75F", text="@banana"
    )


def test_panel_titles_track_alphabetical_slot_order() -> None:
    """Slot identity is by index, not tribe — titles follow alphabetic order
    of the current tribe set, not insertion order of the agents.
    """
    agents = [
        _agent(name="z1", tribe="zulu", suffix="t1"),
        _agent(name="a1", tribe="alpha", suffix="t2"),
        _agent(name="m1", tribe="mike", suffix="t3"),
    ]
    app = _FakeApp(agents)
    app._refresh_panel_widgets(jump_hints=None)

    assert app._panel_group.panel_keys == ["alpha", "mike", "zulu"]
    assert (
        _title_text(app._panel_widgets["agent-list-panel"]).plain == "@alpha · 1 [R1]"
    )
    assert (
        _title_text(app._panel_widgets["agent-list-panel-1"]).plain == "@mike · 1 [R1]"
    )
    assert (
        _title_text(app._panel_widgets["agent-list-panel-2"]).plain == "@zulu · 1 [R1]"
    )
    assert "agent-list-panel-3" not in app._panel_widgets


def test_panel_title_counts_are_scoped_to_each_panel() -> None:
    agents = [
        _agent(name="wait", suffix="u1", status="WAITING"),
        _agent(name="ask", tribe="apple", suffix="a1", status="QUESTION"),
        _agent(name="starting", tribe="apple", suffix="a3", status="STARTING"),
        _agent(name="run", tribe="apple", suffix="a2", status="RUNNING"),
        _agent(name="fail", tribe="banana", suffix="b1", status="FAILED"),
        _agent(name="unread", tribe="banana", suffix="b2", status="DONE"),
        _agent(name="read", tribe="banana", suffix="b3", status="DONE"),
    ]
    app = _FakeApp(agents)
    app._unread_completed_agent_ids.add(agents[5].identity)

    app._refresh_panel_widgets(jump_hints=None)

    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == (
        "(no tribe) · 1 [W1]"
    )
    assert _title_text(app._panel_widgets["agent-list-panel-1"]).plain == (
        "@apple · 2 [S1 R1]"
    )
    assert _title_text(app._panel_widgets["agent-list-panel-2"]).plain == (
        "@banana · 3 [F1 U1 D1]"
    )
    no_tribe_title = _title_text(app._panel_widgets["agent-list-panel"])
    apple_title = _title_text(app._panel_widgets["agent-list-panel-1"])
    banana_title = _title_text(app._panel_widgets["agent-list-panel-2"])
    _assert_title_metric_styles(
        no_tribe_title,
        neutral_ranges=[(10, 17), (18, 19)],
        metric_digits=[(17, "waiting")],
    )
    _assert_title_metric_styles(
        apple_title,
        neutral_ranges=[(10, 13), (14, 16), (17, 18)],
        metric_digits=[(13, "asking"), (16, "running")],
    )
    _assert_title_metric_styles(
        banana_title,
        neutral_ranges=[(11, 14), (15, 16), (18, 20), (21, 22)],
        metric_digits=[
            (14, "failed"),
            (16, "unread"),
            (17, "unread"),
            (20, "read"),
        ],
    )


def test_panel_title_unread_and_read_counts_are_panel_scoped() -> None:
    agents = [
        _agent(name="apple-unread", tribe="apple", suffix="a1", status="DONE"),
        _agent(name="apple-read", tribe="apple", suffix="a2", status="DONE"),
        _agent(name="banana-unread", tribe="banana", suffix="b1", status="DONE"),
        _agent(name="banana-read", tribe="banana", suffix="b2", status="DONE"),
    ]
    app = _FakeApp(agents)
    app._unread_completed_agent_ids.update({agents[0].identity, agents[2].identity})

    app._refresh_panel_widgets(jump_hints=None)

    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == (
        "@apple · 2 [U1 D1]"
    )
    assert _title_text(app._panel_widgets["agent-list-panel-1"]).plain == (
        "@banana · 2 [U1 D1]"
    )


def test_panel_titles_omit_starting_shorthand_for_hidden_starting_agents() -> None:
    agents = [
        _agent(name="starting", tribe="apple", suffix="a1", status="STARTING"),
        _agent(name="running", tribe="apple", suffix="a2", status="RUNNING"),
    ]
    app = _FakeApp(agents)

    app._refresh_panel_widgets(jump_hints=None)

    apple_title = _title_text(app._panel_widgets["agent-list-panel"])
    assert app._panel_group.panel_keys == ["apple"]
    assert apple_title.plain == "@apple · 1 [R1]"
    assert "T" not in apple_title.plain
    assert "agent-list-panel-1" not in app._panel_widgets


def test_panel_title_shorthand_counts_only_top_level_agents() -> None:
    agents = [
        _agent(name="parent", tribe="apple", suffix="parent", status="RUNNING"),
        _agent(
            name="child",
            suffix="child",
            status="FAILED",
            parent_timestamp="parent",
        ),
    ]
    app = _FakeApp(agents)

    app._refresh_panel_widgets(jump_hints=None)

    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == (
        "@apple · 2 [R1]"
    )


def test_panel_title_projects_parallel_family_member_statuses_per_panel() -> None:
    ordinary_running = _agent(
        name="ordinary-running",
        tribe="apple",
        suffix="ordinary-running",
    )
    apple_root = _agent(
        name="apple-family",
        tribe="apple",
        suffix="apple-root",
        status="WAITING",
        agent_family_parallel=True,
    )
    apple_members = [
        _agent(
            name=f"apple-{status.lower()}-{index}",
            suffix=f"apple-member-{index}",
            status=status,
            parent_timestamp=apple_root.raw_suffix,
            agent_family_parallel=True,
        )
        for index, status in enumerate(
            ("RUNNING", "STARTING", "WAITING", "DONE", "DONE")
        )
    ]
    apple_serial_child = _agent(
        name="apple-serial-failed",
        suffix="apple-serial",
        status="FAILED",
        parent_timestamp=apple_root.raw_suffix,
    )
    apple_root.runtime_children.extend([*apple_members, apple_serial_child])

    banana_root = _agent(
        name="banana-family",
        tribe="banana",
        suffix="banana-root",
        status="RUNNING",
        agent_family_parallel=True,
    )
    banana_members = [
        _agent(
            name=f"banana-{status.lower()}-{index}",
            suffix=f"banana-member-{index}",
            status=status,
            parent_timestamp=banana_root.raw_suffix,
            agent_family_parallel=True,
        )
        for index, status in enumerate(("QUESTION", "FAILED", "DONE"))
    ]
    banana_serial_child = _agent(
        name="banana-serial-running",
        suffix="banana-serial",
        parent_timestamp=banana_root.raw_suffix,
    )
    banana_root.runtime_children.extend([*banana_members, banana_serial_child])

    agents = [
        ordinary_running,
        apple_root,
        *apple_members,
        apple_serial_child,
        banana_root,
        *banana_members,
        banana_serial_child,
    ]
    app = _FakeApp(agents)
    app._unread_completed_agent_ids.update(
        {
            apple_members[3].identity,
            apple_serial_child.identity,
        }
    )

    app._refresh_panel_widgets(jump_hints=None)

    # Hidden family members replace the aggregate root status in each chip,
    # while the existing panel row totals and panel scoping stay unchanged.
    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == (
        "@apple · 7 [R3 W1 U1 D1]"
    )
    assert _title_text(app._panel_widgets["agent-list-panel-1"]).plain == (
        "@banana · 5 [S1 F1 D1]"
    )


def test_panel_title_projects_sequential_family_members_concretely() -> None:
    planner = _agent(
        name="build--plan",
        tribe="apple",
        suffix="build-plan",
        status="TALE APPROVED",
    )
    planner.agent_family = "build"
    planner.agent_family_role = "root"
    planner.role_suffix = "--plan"
    coder = _agent(
        name="build--code",
        suffix="build-code",
        status="WORKING TALE",
        parent_timestamp=planner.raw_suffix,
    )
    coder.agent_family = "build"
    coder.agent_family_role = "code"
    coder.role_suffix = "--code"
    planner.followup_agents = [coder]
    app = _FakeApp([planner, coder])

    app._refresh_panel_widgets(jump_hints=None)

    assert _title_text(app._panel_widgets["agent-list-panel"]).plain == (
        "@apple · 2 [R1 D1]"
    )


def test_grouped_panel_title_uses_all_agents_label_with_counts() -> None:
    agents = [
        _agent(name="no_tribe", suffix="u1", status="RUNNING"),
        _agent(name="tribe_assigned", tribe="apple", suffix="a1", status="WAITING"),
    ]
    app = _FakeApp(agents, merge_tribe_panels=True)

    app._refresh_panel_widgets(jump_hints=None)

    title = _title_text(app._panel_widgets["agent-list-panel"])
    assert title.plain == "All agents · 2 [R1 W1]"
    _assert_title_span(title, start=0, end=10, style="bold #AFFFFF", text="All agents")
