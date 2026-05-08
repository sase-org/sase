"""Tests for dismissed-name rewrite behavior during agent dismissal."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import AgentType

from tests._agent_dismiss_helpers import (
    FakeDismissApp,
    make_agent,
    patch_isolated_home,
)


def test_dismiss_renames_named_agent_with_date_prefix(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Dismissing ``foo`` on April 28 2026 yields ``260428.foo``."""
    app = FakeDismissApp()
    agent = make_agent(
        cl_name="feature_a",
        raw_suffix="20260428100000",
        stop_time=datetime(2026, 4, 28, 12, 0, 0),
        agent_name="foo",
    )
    app._agents_with_children = [agent]

    patches = patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._dismiss_done_agent(agent)
    finally:
        for p in patches:
            p.stop()

    assert agent.agent_name == "260428.foo"
    assert app._dismissed_agent_objects == [agent]
    assert app._dismissed_agent_objects[0].agent_name == "260428.foo"


def test_dismiss_unnamed_agent_gets_prefixed_name(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """An agent with no ``agent_name`` still receives a non-empty prefix."""
    app = FakeDismissApp()
    agent = make_agent(
        cl_name="feature_b",
        raw_suffix="20260428100000",
        stop_time=datetime(2026, 4, 28, 12, 0, 0),
    )
    app._agents_with_children = [agent]

    patches = patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._dismiss_done_agent(agent)
    finally:
        for p in patches:
            p.stop()

    assert agent.agent_name == "260428.feature_b"


def test_batch_dismiss_unique_names_for_same_day_same_base(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two same-day agents with name ``foo`` get unique dismissed names."""
    app = FakeDismissApp()
    a1 = make_agent(
        cl_name="cl_a",
        raw_suffix="20260428100000",
        stop_time=datetime(2026, 4, 28, 12, 0, 0),
        agent_name="foo",
    )
    a2 = make_agent(
        cl_name="cl_b",
        raw_suffix="20260428110000",
        stop_time=datetime(2026, 4, 28, 13, 0, 0),
        agent_name="foo",
    )
    app._agents_with_children = [a1, a2]
    app._agents = [a1, a2]

    patches = patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._do_dismiss_all([a1, a2])
    finally:
        for p in patches:
            p.stop()

    names = sorted(a.agent_name or "" for a in [a1, a2])
    assert names == ["260428.foo", "260428.foo_2"]


def test_dismiss_renames_named_workflow_children(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Workflow children with names also pick up the dismissal prefix."""
    app = FakeDismissApp()
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000",
        workflow="wf",
        stop_time=datetime(2026, 4, 28, 12, 0, 0),
        agent_name="root",
    )
    named_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000_c0",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
        agent_name="root.plan",
    )
    unnamed_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="cl_a",
        raw_suffix="20260428100000_c1",
        parent_workflow="wf",
        parent_timestamp="20260428100000",
    )
    app._agents_with_children = [parent, named_child, unnamed_child]

    patches = patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._dismiss_done_agent(parent)
    finally:
        for p in patches:
            p.stop()

    assert parent.agent_name == "260428.root"
    assert named_child.agent_name == "260428.root.plan"
    assert unnamed_child.agent_name is None


def test_dismiss_rename_uses_start_time_when_stop_time_missing(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Falls back to ``start_time`` when ``stop_time`` is None."""
    app = FakeDismissApp()
    agent = make_agent(
        cl_name="feature_c",
        raw_suffix="20260427100000",
        start_time=datetime(2026, 4, 27, 9, 0, 0),
        stop_time=None,
        agent_name="bar",
    )
    app._agents_with_children = [agent]

    patches = patch_isolated_home(tmp_path)
    for p in patches:
        p.start()
    try:
        app._dismiss_done_agent(agent)
    finally:
        for p in patches:
            p.stop()

    assert agent.agent_name == "260427.bar"
