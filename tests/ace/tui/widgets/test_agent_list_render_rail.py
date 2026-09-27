"""Tests for the pure node-rail vocabulary module."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, GroupRow
from sase.ace.tui.widgets._agent_list_render_agent_prefix import (
    append_agent_row_prefix,
)
from sase.ace.tui.widgets._agent_list_render_rail import (
    NODE_RAIL_WIDTH,
    RAIL_BUCKET_GLYPHS,
    RAIL_CONTENT_CELLS,
    RAIL_COUNT_CAP,
    RAIL_LEGEND,
    RAIL_MAX_DEPTH,
    RAIL_TITLE_CELLS,
    rail_agent_cells,
    rail_banner_cells,
    rail_overflow_subtitle,
    rail_panel_title,
    rail_tooltip_text,
    rail_urgency,
    row_kind_glyph,
)

# Glyphs the research banned from the rail: hourglass/waiting emoji
# register, lightning, maximize, and timeout glyphs, plus emoji generally.
BANNED_GLYPHS = {"⏳", "⚡", "⤢", "⧖", "…", "▲"}

_START = datetime(2026, 6, 23, 12, 0, 0)


def _agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "demo",
        "project_file": "/tmp/projects/proj_a/proj_a.sase",
        "status": "RUNNING",
        "start_time": _START,
        "raw_suffix": "20260623120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


def _ctx(**overrides: object) -> dict[str, object]:
    ctx: dict[str, object] = {
        "hint_char": None,
        "is_unread": False,
        "is_marked": False,
    }
    ctx.update(overrides)
    return ctx


def _monitor(**overrides: object) -> Agent:
    kw: dict[str, object] = {
        "agent_session_role": "monitor",
        "role_suffix": "--mon",
        "monitor_id": "m1",
        "monitor_state": "running",
        "parent_timestamp": "20260623115900",
    }
    kw.update(overrides)
    return _agent(**kw)


def _gate(**overrides: object) -> Agent:
    kw: dict[str, object] = {
        "agent_session_role": "gate",
        "role_suffix": "--gate",
        "gate_id": "g1",
        "gate_state": "running",
        "parent_timestamp": "20260623115900",
    }
    kw.update(overrides)
    return _agent(**kw)


def _group(
    *,
    level: int = 0,
    key: tuple[str, ...] = ("proj",),
    collapsed: bool = False,
    has_children: bool = False,
) -> GroupRow:
    return GroupRow(
        level=level,
        group_key=key,
        agent_indices=(0,),
        is_collapsed=collapsed,
        has_child_groups=has_children,
    )


def test_constants() -> None:
    assert NODE_RAIL_WIDTH == 9
    assert RAIL_CONTENT_CELLS == 6
    assert RAIL_TITLE_CELLS == 5
    assert RAIL_MAX_DEPTH == 2
    assert RAIL_COUNT_CAP == 99
    assert set(RAIL_BUCKET_GLYPHS) == {
        "Stopped",
        "Failed",
        "Starting",
        "Running",
        "Queued",
        "Waiting",
        "Done",
    }


def _bucket_agents() -> list[Agent]:
    return [
        _agent(status="QUESTION"),
        _agent(status="PLAN"),
        _agent(status="FAILED"),
        _agent(status="STARTING"),
        _agent(status="RUNNING"),
        _agent(status="QUEUED"),
        _agent(status="WAITING"),
        _agent(status="DONE"),
        _agent(status="STOPPED"),
    ]


def _kind_agents() -> list[Agent]:
    child = _agent(
        parent_workflow="flow",
        step_type="python",
        agent_type=AgentType.WORKFLOW,
    )
    agent_step = _agent(
        parent_workflow="flow",
        step_type="agent",
        agent_type=AgentType.WORKFLOW,
    )
    clan_child = _agent(agent_name="map.one", agent_clan="map")
    clan = _agent(is_clan_container=True, agent_clan="map")
    clan.runtime_children = [clan_child]
    session_child = _agent(agent_session="alpha", role_suffix="--code")
    session = _agent(
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
        plan_chain_root=True,
    )
    session.followup_agents = [session_child]
    assert session.is_agent_session_container_row
    return [
        _agent(),
        _monitor(),
        _monitor(monitor_state="completed", stop_time=_START),
        _gate(),
        _gate(gate_state="failed"),
        _agent(agent_type=AgentType.NAMED_PROC),
        child,
        agent_step,
        _agent(agent_type=AgentType.WORKFLOW, appears_as_agent=True),
        clan,
        session,
    ]


def test_agent_cells_exact_width_exhaustive() -> None:
    ctx_variants = [
        _ctx(),
        _ctx(is_unread=True),
        _ctx(is_marked=True),
        _ctx(is_marked=True, is_unread=True),
        _ctx(hint_char="a"),
        _ctx(hint_char="ab"),
        _ctx(hint_char="a", is_unread=True),
        _ctx(hint_char="ab", is_marked=True),
    ]
    agents = _bucket_agents() + _kind_agents()
    for agent in agents:
        for ctx in ctx_variants:
            for depth in range(5):
                cells = rail_agent_cells(agent, ctx, depth=depth)
                assert cells.cell_len == RAIL_CONTENT_CELLS, (
                    agent.status,
                    agent.agent_type,
                    ctx,
                    depth,
                    repr(cells.plain),
                )


def test_agent_cells_glyph_choices() -> None:
    assert rail_agent_cells(_agent(status="QUESTION"), _ctx(), depth=0).plain[0] == "?"
    assert rail_agent_cells(_agent(status="FAILED"), _ctx(), depth=0).plain[0] == "✗"
    assert rail_agent_cells(_agent(status="RUNNING"), _ctx(), depth=0).plain[0] == "▶"
    assert rail_agent_cells(_agent(status="QUEUED"), _ctx(), depth=0).plain[0] == "○"
    assert rail_agent_cells(_agent(status="WAITING"), _ctx(), depth=0).plain[0] == "◷"
    assert rail_agent_cells(_agent(status="STARTING"), _ctx(), depth=0).plain[0] == "◐"
    assert rail_agent_cells(_agent(status="STOPPED"), _ctx(), depth=0).plain[0] == "Ø"
    done_unread = rail_agent_cells(_agent(status="DONE"), _ctx(is_unread=True), depth=0)
    assert done_unread.plain[0] == "✓"
    assert done_unread.plain[-1] == "•"
    done_read = rail_agent_cells(_agent(status="DONE"), _ctx(), depth=0)
    assert done_read.plain[0] == "✓"
    assert done_read.plain[-1] == " "
    marked = rail_agent_cells(_agent(status="RUNNING"), _ctx(is_marked=True), depth=0)
    assert marked.plain[-1] == "▪"
    # Marked wins over unread.
    both = rail_agent_cells(
        _agent(status="RUNNING"), _ctx(is_marked=True, is_unread=True), depth=0
    )
    assert both.plain[-1] == "▪"


def test_agent_cells_hint_replaces_glyph() -> None:
    one = rail_agent_cells(_agent(status="RUNNING"), _ctx(hint_char="q"), depth=0)
    assert one.plain[0] == "q"
    two = rail_agent_cells(_agent(status="RUNNING"), _ctx(hint_char="qd"), depth=0)
    assert two.plain[:2] == "qd"
    assert two.cell_len == RAIL_CONTENT_CELLS


def test_agent_cells_depth_guides_and_clamp() -> None:
    assert rail_agent_cells(_agent(), _ctx(), depth=1).plain[0] == "└"
    deep = rail_agent_cells(_agent(), _ctx(), depth=2)
    assert deep.plain[:2] == "│└"
    assert rail_agent_cells(_agent(), _ctx(), depth=3).plain == deep.plain
    assert rail_agent_cells(_agent(), _ctx(), depth=4).plain == deep.plain
    assert (
        rail_agent_cells(_agent(), _ctx(), depth=-1).plain
        == rail_agent_cells(_agent(), _ctx(), depth=0).plain
    )


def test_agent_cells_container_counts() -> None:
    clan_child = _agent(agent_name="map.one", agent_clan="map")
    clan = _agent(is_clan_container=True, agent_clan="map")
    clan.runtime_children = [clan_child, clan_child]
    cells = rail_agent_cells(clan, _ctx(), depth=0)
    # Duplicate identities count once, like the expanded member chip.
    assert cells.plain[1:3] == " 1"
    many = _agent(is_clan_container=True, agent_clan="map")
    many.runtime_children = [
        _agent(
            agent_name=f"m.{i}",
            agent_clan="map",
            raw_suffix=f"202606231200{i:02d}",
        )
        for i in range(150)
    ]
    assert rail_agent_cells(many, _ctx(), depth=0).plain[1:3] == "99"


def test_banner_cells_exact_width_exhaustive() -> None:
    agents = [_agent(), _agent(status="FAILED")]
    modes = list(GroupingMode)
    for mode in modes:
        for level in range(4):
            for collapsed in (False, True):
                for hint in (None, "a", "ab"):
                    group = _group(
                        level=level,
                        key=("b",) if level == 0 else ("b", "sub"),
                        collapsed=collapsed,
                    )
                    cells = rail_banner_cells(
                        group, agents, mode=mode, hint=hint, mark_state="all"
                    )
                    assert cells.cell_len == RAIL_CONTENT_CELLS, (
                        mode,
                        level,
                        collapsed,
                        hint,
                        repr(cells.plain),
                    )


def test_banner_cells_expanded_layout() -> None:
    agents = [_agent()]
    l0 = rail_banner_cells(_group(level=0), agents)
    assert l0.plain[0] == "p"
    assert l0.plain[1:] == "━" * 5
    l1 = rail_banner_cells(_group(level=1, key=("b", "sub")), agents)
    assert l1.plain[1:] == "─" * 5


def test_banner_cells_folded_layout() -> None:
    agents = [_agent(), _agent(status="FAILED"), _agent(status="DONE")]
    group = GroupRow(
        level=0,
        group_key=("proj",),
        agent_indices=(0, 1, 2),
        is_collapsed=True,
    )
    cells = rail_banner_cells(group, agents)
    assert cells.plain[0] == "▸"
    assert cells.plain[4] == "3"
    # A failed member rolls up red.
    assert cells.plain[5] == "✗"
    hinted = rail_banner_cells(group, agents, hint="q")
    assert hinted.plain[0] == "q"
    assert hinted.cell_len == RAIL_CONTENT_CELLS


def test_banner_cells_bucket_lead_parity() -> None:
    for bucket, (glyph, _style) in RAIL_BUCKET_GLYPHS.items():
        agents = [_agent()]
        group = _group(level=0, key=(bucket,), collapsed=False)
        cells = rail_banner_cells(group, agents, mode=GroupingMode.BY_STATUS)
        assert cells.plain[0] == glyph, bucket
        machine = _group(level=1, key=("here", bucket), collapsed=False)
        mid = rail_banner_cells(machine, agents, mode=GroupingMode.BY_MACHINE)
        assert mid.plain[0] == glyph, bucket


def test_rail_urgency_precedence() -> None:
    stopped = _agent(status="QUESTION")
    failed = _agent(status="FAILED")
    done = _agent(status="DONE")
    assert rail_urgency([stopped, failed], []).plain == "?"
    assert rail_urgency([failed, done], []).plain == "✗"
    assert rail_urgency([done], [done.identity]).plain == "•"
    assert rail_urgency([done], []).plain == " "
    assert rail_urgency([], []).plain == " "


def test_panel_title_width_and_drop_order() -> None:
    from sase.ace.tui.actions.agents._display_panel_titles import AgentPanelCounts

    counts = AgentPanelCounts(lane_count=3, failed=1)
    # Over budget: 2-char hint + mark + 2-cell icon + urgency drops the mark.
    title = rail_panel_title(
        key="agents",
        hint="ab",
        selected=True,
        collapsed=True,
        icon="xy",
        color="#FF0000",
        counts=counts,
    )
    assert title.cell_len <= RAIL_TITLE_CELLS
    assert "ab" in title.plain
    assert "▸" not in title.plain
    assert "✗" in title.plain
    # Hint is never dropped.
    assert "ab" in title.plain
    # Wide emoji icons fall back to the uppercase initial.
    emoji = rail_panel_title(key="agents", icon="🤖x", color="#00FF00")
    assert emoji.cell_len <= RAIL_TITLE_CELLS
    assert emoji.plain == "A"
    # Merged panel shows All.
    merged = rail_panel_title(key="agents", merged=True)
    assert merged.plain == "All"
    # Selected focus marker.
    assert rail_panel_title(key="agents", selected=True).plain == "❖A"
    # Collapsed marker, gold when selected.
    assert rail_panel_title(key="agents", collapsed=True).plain[0] == "▸"
    # Long names and 2-character hints stay within budget.
    long_name = rail_panel_title(
        key="a-very-long-tribe-name", hint="xy", selected=True, collapsed=True
    )
    assert long_name.cell_len <= RAIL_TITLE_CELLS
    assert "xy" in long_name.plain


def test_overflow_subtitle() -> None:
    assert rail_overflow_subtitle(0, 0).plain == ""
    assert rail_overflow_subtitle(3, 0).plain == "▴3"
    assert rail_overflow_subtitle(0, 12).plain == "▾12"
    assert rail_overflow_subtitle(12, 3).plain == "▴12▾3"
    degraded = rail_overflow_subtitle(123, 45)
    assert degraded.plain == "▴▾"
    assert degraded.cell_len <= RAIL_TITLE_CELLS


def test_tooltip_text() -> None:
    assert rail_tooltip_text(Text("")) is None
    assert rail_tooltip_text(Text("   ")) is None
    assert rail_tooltip_text(Text("name (RUNNING)      2 running")).plain == (
        "name (RUNNING)  2 running"
    )


def test_legend_entries() -> None:
    assert len(RAIL_LEGEND) >= 12
    for glyph, meaning in RAIL_LEGEND:
        assert glyph.cell_len == 1
        assert meaning.strip()


def test_rail_glyphs_single_cell_and_banned() -> None:
    texts = [Text(glyph, style=style) for glyph, style in RAIL_BUCKET_GLYPHS.values()]
    texts += [glyph for glyph, _meaning in RAIL_LEGEND]
    for agent in _bucket_agents() + _kind_agents():
        texts.append(rail_agent_cells(agent, _ctx(), depth=0))
        texts.append(rail_agent_cells(agent, _ctx(hint_char="ab"), depth=2))
    for group_collapsed in (False, True):
        texts.append(
            rail_banner_cells(_group(collapsed=group_collapsed), [_agent()], hint="ab")
        )
    texts.append(rail_overflow_subtitle(3, 4))
    for text in texts:
        for char in text.plain:
            if char == " ":
                continue
            assert Text(char).cell_len == 1, repr(char)
            assert char not in BANNED_GLYPHS, repr(char)


def test_row_kind_glyph_parity_with_expanded_prefix() -> None:
    for agent in _kind_agents():
        kind = row_kind_glyph(agent)
        prefix = append_agent_row_prefix(agent, is_selected=False).plain
        if kind is None:
            continue
        glyph, _style = kind
        assert glyph in prefix, (glyph, prefix)
    # Plain agents have no kind badge; the expanded row keeps its [agent] tag.
    plain = _agent()
    assert row_kind_glyph(plain) is None
    assert "[agent]" in append_agent_row_prefix(plain, is_selected=False).plain
    # Expanded anonymous workflows show the workflow badge in both densities.
    workflow = _agent(
        agent_type=AgentType.WORKFLOW, appears_as_agent=True, is_anonymous=True
    )
    assert row_kind_glyph(workflow, is_expanded=True) == (
        "≡",
        "bold #FF87D7",
    )
    assert (
        "≡"
        in append_agent_row_prefix(workflow, is_selected=False, is_expanded=True).plain
    )
    rail_cells = rail_agent_cells(workflow, _ctx(is_expanded=True), depth=0)
    assert rail_cells.plain[0] == "≡"
    assert rail_cells.cell_len == RAIL_CONTENT_CELLS


@pytest.mark.parametrize("bucket", list(RAIL_BUCKET_GLYPHS))
def test_banner_glyph_matches_rail_glyph(bucket: str) -> None:
    """Each bucket banner glyph equals the rail glyph for that bucket."""
    glyph, _style = RAIL_BUCKET_GLYPHS[bucket]
    assert Text(glyph).cell_len == 1
