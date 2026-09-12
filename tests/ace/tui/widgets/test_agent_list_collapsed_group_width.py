"""Collapsed groups must not keep the Agents panel as wide as hidden rows."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.widgets._agent_list_build import patch_row, visible_agent_indices
from sase.ace.tui.widgets._agent_list_styling import _MIN_BANNER_WIDTH
from sase.ace.tui.widgets.agent_list import AgentList, _BANNER_ROW

from ._agent_list_grouping_helpers import make_agent

_NOW = datetime(2026, 4, 25, 21, 0, 0)
_PADDING = 8

_SHORT_NAME = "alpha-row"
_LONG_NAME = (
    "bravo-this-agent-name-is-markedly-longer-than-alpha-and-drives-panel-width"
)


def _two_project_agents() -> list[Agent]:
    return [
        make_agent(
            cl_name=_SHORT_NAME,
            project_file="/r/projA/proj.sase",
            start_time=datetime(2026, 4, 25, 14, 0, 0),
        ),
        make_agent(
            cl_name=_LONG_NAME,
            project_file="/r/projB/proj.sase",
            start_time=datetime(2026, 4, 25, 14, 0, 0),
        ),
    ]


def _render(
    agents: list[Agent],
    *,
    collapsed: tuple[str, ...] = (),
) -> AgentList:
    registry = AgentGroupFoldRegistry()
    for key in collapsed:
        registry.collapse((key,))
    widget = AgentList()
    widget.update_list(agents, current_idx=0, fold_registry=registry, now=_NOW)
    return widget


def _agent_row_cell_lens(widget: AgentList) -> list[int]:
    lengths: list[int] = []
    options = list(widget._options)
    for row, entry in enumerate(widget._row_entries):
        if entry[0] == _BANNER_ROW:
            continue
        prompt = options[row].prompt
        assert isinstance(prompt, Text)
        lengths.append(prompt.cell_len)
    return lengths


def test_collapsing_the_widest_group_shrinks_the_panel() -> None:
    agents = _two_project_agents()
    expanded = _render(agents)
    expanded_target = expanded._target_width
    expanded_requested = expanded._requested_width

    collapsed = _render(agents, collapsed=("projB",))
    assert collapsed._target_width < expanded_target
    assert collapsed._requested_width < expanded_requested

    only_visible = _render([agents[0]])
    assert collapsed._target_width == only_visible._target_width


def test_expanding_restores_the_previous_width() -> None:
    agents = _two_project_agents()
    original = _render(agents)._requested_width
    collapsed = _render(agents, collapsed=("projB",))
    assert collapsed._requested_width < original
    restored = _render(agents)
    assert restored._requested_width == original


def test_hidden_row_suffix_does_not_stretch_alignment_column() -> None:
    visible = make_agent(
        cl_name="short-visible",
        project_file="/r/projA/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 20, 0, 0),
        run_start_time=datetime(2026, 4, 25, 20, 0, 0),
    )
    hidden = make_agent(
        cl_name="short-hidden",
        project_file="/r/projB/proj.sase",
        status="DONE",
        start_time=datetime(2026, 4, 24, 19, 38, 18),
        run_start_time=datetime(2026, 4, 24, 19, 38, 18),
        stop_time=datetime(2026, 4, 24, 20, 17, 3),
    )
    agents = [visible, hidden]
    expanded = _render(agents)
    collapsed = _render(agents, collapsed=("projB",))
    assert collapsed._target_width < expanded._target_width
    agent_lens = _agent_row_cell_lens(collapsed)
    assert agent_lens
    assert all(cell_len == collapsed._target_width for cell_len in agent_lens)


def test_published_width_covers_emitted_banners() -> None:
    visible = make_agent(
        cl_name="a",
        project_file="/r/projA/proj.sase",
        start_time=datetime(2026, 4, 25, 14, 0, 0),
    )
    hidden: list[Agent] = []
    for i in range(10):
        hidden.append(
            make_agent(
                cl_name=f"run-{i}",
                project_file="/r/projB/proj.sase",
                status="RUNNING",
                start_time=datetime(2026, 4, 25, 14, 0, 0),
            )
        )
    for i in range(8):
        hidden.append(
            make_agent(
                cl_name=f"fail-{i}",
                project_file="/r/projB/proj.sase",
                status="FAILED",
                start_time=datetime(2026, 4, 25, 14, 0, 0),
            )
        )
    for i in range(7):
        hidden.append(
            make_agent(
                cl_name=f"stop-{i}",
                project_file="/r/projB/proj.sase",
                status="STOPPED",
                start_time=datetime(2026, 4, 25, 14, 0, 0),
            )
        )
    widget = _render([visible, *hidden], collapsed=("projB",))
    option_lens = [
        option.prompt.cell_len
        for option in widget._options
        if isinstance(option.prompt, Text)
    ]
    assert option_lens
    assert max(option_lens) + _PADDING <= widget._requested_width

    collapsed_banner_lens = [
        widget._options[row].prompt.cell_len
        for row in widget._banner_at_row
        if isinstance(widget._options[row].prompt, Text)
    ]
    assert collapsed_banner_lens
    # A collapsed banner may exceed the agent-row column; it must not
    # exceed the published panel width (already asserted above).
    assert any(cell_len > widget._target_width for cell_len in collapsed_banner_lens)


def test_hidden_agents_are_not_rendered_or_measured() -> None:
    agents = _two_project_agents()
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projB",))
    widget = AgentList()
    widget.update_list(agents, current_idx=0, fold_registry=registry, now=_NOW)
    tree = build_agent_tree(agents, fold_registry=registry)
    visible = visible_agent_indices(tree)
    assert set(widget._row_render_ctx) == visible
    assert set(widget._row_tier_styles) == visible
    hidden = next(i for i in range(len(agents)) if i not in visible)
    assert patch_row(widget, hidden) is False


def test_floor_holds_when_every_group_is_collapsed() -> None:
    agents = _two_project_agents()
    widget = _render(agents, collapsed=("projA", "projB"))
    assert widget._target_width == _MIN_BANNER_WIDTH
    plains = [
        option.prompt.plain
        for option in widget._options
        if isinstance(option.prompt, Text) and option.prompt.plain
    ]
    assert any("projA" in plain and "agent" in plain for plain in plains)
    assert any("projB" in plain and "agent" in plain for plain in plains)
