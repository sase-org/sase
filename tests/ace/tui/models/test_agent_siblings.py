"""Tests for the Agents-tab sibling index model."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.agent_siblings import (
    AgentSiblingIndex,
    AgentSiblingRow,
    agent_sibling_family,
)


def _agent(
    name: str | None,
    *,
    status: str = "RUNNING",
    tag: str | None = None,
    suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/r/proj/proj.sase",
        status=status,
        start_time=datetime(2026, 5, 23, 12, 0, 0),
        raw_suffix=suffix or name,
        agent_name=name,
        tag=tag,
    )


def _rows_from_tree(
    agents: list[Agent], registry: AgentGroupFoldRegistry
) -> list[AgentSiblingRow]:
    tree = build_agent_tree(agents, fold_registry=registry)
    return [
        AgentSiblingRow(entry.agent_idx, 0, agents[entry.agent_idx])
        for entry in tree
        if entry.kind == "agent" and entry.agent_idx is not None
    ]


def test_agent_sibling_family_uses_first_dotted_segment() -> None:
    assert agent_sibling_family(_agent("foo.bar")) == "foo"
    assert agent_sibling_family(_agent("foo.bar.baz")) == "foo"


def test_agent_sibling_family_rejects_dotless_or_empty_segments() -> None:
    assert agent_sibling_family(_agent("foo")) is None
    assert agent_sibling_family(_agent(".bar")) is None
    assert agent_sibling_family(_agent("foo.")) is None
    assert agent_sibling_family(_agent(None)) is None


def test_agent_sibling_family_matches_case_insensitively() -> None:
    assert agent_sibling_family(_agent("Foo.plan")) == "foo"
    assert agent_sibling_family(_agent("foo.code")) == "foo"


def test_sibling_index_excludes_current_agent_and_dotless_names() -> None:
    rows = [
        AgentSiblingRow(0, 0, _agent("foo.plan")),
        AgentSiblingRow(1, 0, _agent("foo.code")),
        AgentSiblingRow(2, 0, _agent("foo.review.pass1")),
        AgentSiblingRow(3, 0, _agent("bar.plan")),
        AgentSiblingRow(4, 0, _agent("foo")),
    ]

    index = AgentSiblingIndex.from_visible_rows(rows)

    assert index.siblings_for(0) == (1, 2)
    assert index.siblings_for(1) == (0, 2)
    assert index.sibling_count(2) == 2
    assert index.siblings_for(3) == ()
    assert index.siblings_for(4) == ()


def test_sibling_index_matches_case_insensitively() -> None:
    rows = [
        AgentSiblingRow(0, 0, _agent("Foo.plan")),
        AgentSiblingRow(1, 0, _agent("foo.code")),
    ]

    index = AgentSiblingIndex.from_visible_rows(rows)

    assert index.siblings_for(0) == (1,)
    assert index.siblings_for(1) == (0,)


def test_sibling_index_excludes_non_rendered_starting_rows() -> None:
    rows = [
        AgentSiblingRow(0, 0, _agent("foo.plan")),
        AgentSiblingRow(1, 0, _agent("foo.starting", status="STARTING")),
        AgentSiblingRow(2, 0, _agent("foo.code")),
    ]

    index = AgentSiblingIndex.from_visible_rows(rows)

    assert index.siblings_for(0) == (2,)
    assert index.siblings_for(1) == ()
    assert index.siblings_for(2) == (0,)


def test_sibling_index_excludes_agents_hidden_by_collapsed_groups() -> None:
    agents = [
        _agent("foo.plan"),
        _agent("foo.code"),
        _agent("bar.plan"),
    ]
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "foo"))

    index = AgentSiblingIndex.from_visible_rows(_rows_from_tree(agents, registry))

    assert index.siblings_for(0) == ()
    assert index.siblings_for(1) == ()
    assert index.siblings_for(2) == ()


def test_sibling_index_preserves_visible_render_order_across_panels() -> None:
    rows = [
        AgentSiblingRow(2, 0, _agent("foo.untagged")),
        AgentSiblingRow(0, 1, _agent("foo.alpha")),
        AgentSiblingRow(1, 2, _agent("foo.zeta")),
    ]

    index = AgentSiblingIndex.from_visible_rows(rows)

    assert index.siblings_for(2) == (0, 1)
    assert index.siblings_for(0) == (2, 1)
    assert index.panel_idx_for(2) == 0
    assert index.panel_idx_for(0) == 1
    assert index.panel_idx_for(1) == 2
