"""Panel title labels refreshed for vertically stacked Agents-tab panels.

Each ``AgentList`` panel must show a ``border_title`` identifying its tribe
(``@default`` / ``@<tribe>``) plus a ``· N`` agent count, refreshed every
time :meth:`AgentDisplayMixin._refresh_panel_widgets` runs (panel widget
ids correspond to index slots, not fixed tribes — alphabetic shifts can
flip which tribe a slot points at).
"""

from __future__ import annotations

from ._agent_panel_title_helpers import (
    _FakeApp,
    _agent,
    _assert_title_metric_styles,
    _assert_title_span,
    _title_text,
)


def test_panel_titles_label_default_and_named_tribes_with_counts() -> None:
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
    assert main_title.plain == "⌂ @default · 2 [R2]"
    _assert_title_span(main_title, start=0, end=2, style="bold #87D7FF", text="⌂ ")
    _assert_title_span(
        main_title, start=2, end=10, style="bold #87D7FF", text="@default"
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
        "⌂ @default · 1 [W1]"
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
