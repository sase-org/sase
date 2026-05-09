"""Tests that agent dismissal hides rows without renaming them."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import AgentType

from tests._agent_dismiss_helpers import (
    FakeDismissApp,
    make_agent,
    patch_isolated_home,
)


def test_dismiss_preserves_named_agent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Dismissing a named agent hides it without changing its name."""
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

    assert agent.agent_name == "foo"
    assert app._dismissed_agent_objects == [agent]
    assert app._dismissed_agent_objects[0].agent_name == "foo"


def test_dismiss_unnamed_agent_stays_unnamed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Dismissal does not synthesize names for unnamed agents."""
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

    assert agent.agent_name is None


def test_batch_dismiss_preserves_same_named_agents(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Batch dismissal leaves existing names untouched."""
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
    assert names == ["foo", "foo"]


def test_dismiss_preserves_named_workflow_children(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Workflow parent and child names survive dismissal unchanged."""
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

    assert parent.agent_name == "root"
    assert named_child.agent_name == "root.plan"
    assert unnamed_child.agent_name is None


def test_dismiss_without_stop_time_preserves_name(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Missing stop time does not trigger any rename fallback."""
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

    assert agent.agent_name == "bar"
