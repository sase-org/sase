"""Tests for collapsed group banner mark indicators."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import GroupRow, GroupingMode, build_agent_tree
from sase.ace.tui.widgets._agent_list_render_banner import format_banner_option
from sase.ace.tui.widgets._agent_list_render_cache import banner_render_key
from sase.ace.tui.widgets.agent_list import AgentList


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/tmp/projects/proj_a/proj_a.sase",
    raw_suffix: str = "20260623120000",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
        start_time=datetime(2026, 6, 23, 12, 0, 0),
        raw_suffix=raw_suffix,
    )


def _first_group(agents: list[Agent]) -> GroupRow:
    tree = build_agent_tree(agents)
    return next(entry.group for entry in tree if entry.group is not None)


def test_format_banner_option_renders_all_mark_indicator() -> None:
    agents = [_agent()]
    group = _first_group(agents)

    option = format_banner_option(
        group,
        agents,
        width=48,
        sequence=0,
        selectable=True,
        mark_state="all",
    )

    assert option.prompt.plain.startswith("[✓] ")


def test_format_banner_option_renders_partial_mark_indicator() -> None:
    agents = [_agent()]
    group = _first_group(agents)

    option = format_banner_option(
        group,
        agents,
        width=48,
        sequence=0,
        selectable=True,
        mark_state="partial",
    )

    assert option.prompt.plain.startswith("[~] ")


def test_banner_render_key_varies_by_mark_state() -> None:
    agents = [_agent()]
    group = _first_group(agents)

    none_key = banner_render_key(
        group,
        agents,
        width=48,
        sequence=0,
        selectable=True,
        mode=GroupingMode.STANDARD,
        tier_styles=(),
        hint_char=None,
        mark_state="none",
    )
    all_key = banner_render_key(
        group,
        agents,
        width=48,
        sequence=0,
        selectable=True,
        mode=GroupingMode.STANDARD,
        tier_styles=(),
        hint_char=None,
        mark_state="all",
    )
    partial_key = banner_render_key(
        group,
        agents,
        width=48,
        sequence=0,
        selectable=True,
        mode=GroupingMode.STANDARD,
        tier_styles=(),
        hint_char=None,
        mark_state="partial",
    )

    assert none_key != all_key
    assert none_key != partial_key
    assert all_key != partial_key


def test_update_list_marks_collapsed_banner_all() -> None:
    agents = [
        _agent(raw_suffix="20260623120000"),
        _agent(raw_suffix="20260623130000"),
    ]
    folds = AgentGroupFoldRegistry()
    folds.collapse(("proj_a",))
    widget = AgentList()

    widget.update_list(
        agents,
        current_idx=0,
        fold_registry=folds,
        marked_agents={agent.identity for agent in agents},
    )

    assert list(widget._options)[0].prompt.plain.startswith("[✓] ")


def test_update_list_marks_collapsed_banner_partial() -> None:
    marked = _agent(raw_suffix="20260623120000")
    unmarked = _agent(raw_suffix="20260623130000")
    folds = AgentGroupFoldRegistry()
    folds.collapse(("proj_a",))
    widget = AgentList()

    widget.update_list(
        [marked, unmarked],
        current_idx=0,
        fold_registry=folds,
        marked_agents={marked.identity},
    )

    assert list(widget._options)[0].prompt.plain.startswith("[~] ")
