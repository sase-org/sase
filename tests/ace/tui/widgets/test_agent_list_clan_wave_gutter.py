"""Visible clan-wave gutters use the five-cell tree prefix."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

from rich.text import Text
from sase.ace.tui.models._agent_clan_waves import ClanWaveSlot
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_cache import agent_render_key
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets._agent_list_render_rail import rail_agent_cells
from sase.ace.tui.widgets._clan_wave_gutter import (
    ClanWaveGutter,
    build_clan_wave_gutters,
)
from sase.ace.tui.widgets._clan_wave_presentation import (
    WAVE_NUMBER_DONE_STYLE,
    WAVE_NUMBER_OPEN_STYLE,
    WAVE_UNRESOLVED_STYLE,
)
from tests.ace.tui.widgets._agent_render_cache_helpers import style_at

_START = datetime(2026, 10, 15, 12, 0, 0)


def _member(
    clan: str,
    suffix: str,
    index: int,
    *,
    waits: tuple[str, ...] = (),
    parent: Agent | None = None,
) -> Agent:
    row = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{clan}.{suffix}",
        project_file="/tmp/waves/project.sase",
        status="WAITING",
        start_time=_START + timedelta(seconds=index),
        raw_suffix=f"20261015{index:06d}",
        agent_name=f"{clan}.{suffix}",
        agent_clan=clan if parent is None else None,
        agent_clan_generation="generation-1" if parent is None else None,
        parent_timestamp=parent.raw_suffix if parent is not None else None,
    )
    row.waiting_for = list(waits)
    return row


def _render_prefix(agent: Agent, index: int, gutter: ClanWaveGutter) -> Text:
    left, _, _ = format_agent_option(
        agent,
        index,
        is_selected=False,
        clan_wave_gutter=gutter,
    )
    return left


def _projected(*members: Agent) -> list[Agent]:
    return project_clan_tree(list(members))


def test_wave_gutter_labels_and_braces_follow_visible_anchor_sequence() -> None:
    first = _member("research", "first", 1)
    second = _member("research", "second", 2)
    later = _member("research", "later", 3, waits=("research.second",))
    rows = _projected(first, second, later)
    gutters = build_clan_wave_gutters(rows, range(1, len(rows)))

    assert gutters[1] == ClanWaveGutter(
        label="1", label_kind="number", bracket="╭", open=True
    )
    assert gutters[2] == ClanWaveGutter(bracket="╰")
    assert gutters[3] == ClanWaveGutter(
        label="2", label_kind="number", bracket="─", open=True
    )
    assert _render_prefix(rows[1], 1, gutters[1]).plain.startswith(" 1 ╭ ")
    assert _render_prefix(rows[2], 2, gutters[2]).plain.startswith("   ╰ ")
    assert _render_prefix(rows[3], 3, gutters[3]).plain.startswith(" 2 ─ ")


def test_query_split_recomputes_brace_from_visible_members() -> None:
    first = _member("research", "first", 1)
    hidden = _member("research", "hidden", 2)
    later = _member("research", "later", 3, waits=("research.hidden",))
    rows = _projected(first, hidden, later)

    gutters = build_clan_wave_gutters(rows, (1, 3))

    assert gutters[1].bracket == "─"
    assert gutters[1].label == "1"
    assert gutters[3].label == "2"


def test_ghost_members_preserve_their_wave_number() -> None:
    live = _member("research", "live", 1, waits=("research.dismissed",))
    rows = _projected(live)
    gutters = build_clan_wave_gutters(rows, (1,))

    assert rows[1].clan_wave_slot is not None
    assert rows[1].clan_wave_slot.wave_index == 2
    assert gutters[1].label == "2"
    assert gutters[1].bracket == "─"


def test_cycle_members_share_an_unresolved_brace() -> None:
    first = _member("cycle", "first", 1, waits=("cycle.second",))
    second = _member("cycle", "second", 2, waits=("cycle.first",))
    rows = _projected(first, second)
    gutters = build_clan_wave_gutters(rows, (1, 2))

    assert gutters[1].label == "?"
    assert gutters[1].bracket == "╭"
    assert gutters[2].label is None
    assert gutters[2].bracket == "╰"
    label = _render_prefix(rows[1], 1, gutters[1])
    assert style_at(label, label.plain.index("?")) == WAVE_UNRESOLVED_STYLE


def test_session_descendant_keeps_a_lane_for_later_same_wave_members() -> None:
    first = _member("research", "family", 1)
    child = _member("research", "family--code", 2, parent=first)
    second = _member("research", "sibling", 3)
    later = _member("research", "later", 4, waits=("research.sibling",))
    rows = _projected(first, child, second, later)
    child_index = next(index for index, row in enumerate(rows) if row is child)
    gutters = build_clan_wave_gutters(rows, range(1, len(rows)))

    assert rows[child_index].tree_depth == 2
    assert gutters[child_index].lane is True
    prefix = _render_prefix(rows[child_index], child_index, gutters[child_index])
    assert prefix.plain.startswith("   │ └─ ")


def test_workflow_step_children_prefer_non_child_suffix_match() -> None:
    parent = _member("research", "workflow", 1)
    first_step = _member("research", "workflow-step-a", 2, parent=parent)
    second_step = _member("research", "workflow-step-b", 3, parent=parent)
    # Workflow steps share their parent's suffix; the suffix map must prefer
    # the non-child row so steps resolve to their parent, not a sibling step.
    first_step.raw_suffix = parent.raw_suffix
    second_step.raw_suffix = parent.raw_suffix
    peer = _member("research", "peer", 4)
    later = _member("research", "later", 5, waits=("research.peer",))
    rows = _projected(parent, first_step, second_step, peer, later)
    step_indices = [
        index
        for index, row in enumerate(rows)
        if row is first_step or row is second_step
    ]

    assert step_indices
    gutters = build_clan_wave_gutters(rows, range(1, len(rows)))
    for step_index in step_indices:
        assert rows[step_index].tree_depth == 2
        assert gutters[step_index].lane is True
        prefix = _render_prefix(rows[step_index], step_index, gutters[step_index])
        assert prefix.plain.startswith("   │ ")


def test_wave_labels_above_99_use_an_ellipsis() -> None:
    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="large",
        project_file="/tmp/waves/project.sase",
        status="RUNNING",
        start_time=_START,
        is_clan_container=True,
        agent_clan="large",
        agent_clan_generation="generation-1",
        clan_waves=SimpleNamespace(layered=True),  # type: ignore[arg-type]
    )
    member = _member("large", "100", 100)
    member.tree_depth = 1
    member.clan_wave_slot = ClanWaveSlot(
        wave_index=100,
        label_kind="number",
        number=100,
        rank=100,
        open=True,
    )
    gutters = build_clan_wave_gutters([container, member], (1,))

    assert gutters[1].label == "…"
    assert _render_prefix(member, 1, gutters[1]).plain.startswith(" … ─ ")


def test_wave_label_state_styles_and_render_cache_key() -> None:
    agent = _member("research", "first", 1)
    agent.tree_depth = 1
    open_gutter = ClanWaveGutter(label="1", label_kind="number", bracket="─", open=True)
    done_gutter = ClanWaveGutter(
        label="1", label_kind="number", bracket="─", open=False
    )
    open_prefix = _render_prefix(agent, 0, open_gutter)
    done_prefix = _render_prefix(agent, 0, done_gutter)
    assert style_at(open_prefix, open_prefix.plain.index("1")) == WAVE_NUMBER_OPEN_STYLE
    assert style_at(done_prefix, done_prefix.plain.index("1")) == WAVE_NUMBER_DONE_STYLE

    kwargs = {
        "is_selected": False,
        "fold_annotation": "",
        "is_expanded": False,
        "is_marked": False,
    }
    assert agent_render_key(agent, 0, **kwargs, clan_wave_gutter=open_gutter) != (
        agent_render_key(agent, 0, **kwargs, clan_wave_gutter=done_gutter)
    )


def test_wave_projection_does_not_change_rail_connectors() -> None:
    member = _member("research", "first", 1)
    member.tree_depth = 1
    member.clan_wave_slot = ClanWaveSlot(
        wave_index=1,
        label_kind="number",
        number=1,
        rank=0,
        open=True,
    )
    without_slot = replace(member, clan_wave_slot=None)

    with_wave = rail_agent_cells(member, {}, depth=1)
    without_wave = rail_agent_cells(without_slot, {}, depth=1)

    assert with_wave.plain == without_wave.plain
