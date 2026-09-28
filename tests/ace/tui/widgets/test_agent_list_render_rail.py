"""Tests for the labeled node-rail vocabulary module."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, GroupRow
from sase.ace.tui.models.agent_relative_label import relative_agent_label
from sase.ace.tui.widgets._agent_list_helpers import (
    compute_fold_annotation,
    folded_member_total,
)
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_render_agent_prefix import (
    append_agent_row_prefix,
)
from sase.ace.tui.widgets._agent_list_render_banner import format_banner_option
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
    _rail_urgency,
    row_kind_glyph,
)
from sase.ace.tui.widgets._agent_list_render_rail_names import (
    rail_middle_elide,
    rail_name_is_dimmed,
    rail_row_name,
)

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
        "folded_total": None,
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
    assert NODE_RAIL_WIDTH == 22
    assert RAIL_CONTENT_CELLS == 19
    assert RAIL_TITLE_CELLS == 18
    assert RAIL_MAX_DEPTH == 3
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
    bash_child = _agent(
        parent_workflow="flow",
        step_type="bash",
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
    named = _agent(agent_type=AgentType.NAMED_PROC, proc_label="lint")
    workflow = _agent(agent_type=AgentType.WORKFLOW, appears_as_agent=True)
    return [
        _agent(),
        _monitor(),
        _monitor(monitor_state="completed", stop_time=_START),
        _gate(),
        _gate(gate_state="failed"),
        named,
        child,
        bash_child,
        agent_step,
        workflow,
        clan,
        session,
    ]


def test_agent_cells_exact_width_exhaustive() -> None:
    names = ["", "a", "2l", "bob-cli-29", "sase-1bn.land", "×" * 2, "研" * 6, "x" * 44]
    ctx_variants = [
        _ctx(),
        _ctx(is_unread=True),
        _ctx(is_marked=True),
        _ctx(is_marked=True, is_unread=True),
        _ctx(hint_char="a"),
        _ctx(hint_char="ab"),
        _ctx(hint_char="a", is_unread=True),
        _ctx(hint_char="ab", is_marked=True),
        _ctx(folded_total=4),
        _ctx(folded_total=99),
        _ctx(folded_total=150),
    ]
    agents = _bucket_agents() + _kind_agents()
    for base in agents:
        for name in names:
            agent = _agent(
                status=base.status,
                agent_type=base.agent_type,
                agent_name=name or base.agent_name,
                raw_suffix=f"20260623120000-{name[:8]}-{base.status}",
            )
            for ctx in ctx_variants:
                for depth in range(6):
                    cells = rail_agent_cells(agent, ctx, depth=depth, anchor_name=None)
                    assert cells.cell_len == RAIL_CONTENT_CELLS, (
                        agent.status,
                        name,
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
    # The name column never moves: 2-char hint takes G plus the space.
    plain_one = rail_agent_cells(
        _agent(agent_name="2l"), _ctx(hint_char="q"), depth=0
    ).plain
    plain_two = rail_agent_cells(
        _agent(agent_name="2l"), _ctx(hint_char="qd"), depth=0
    ).plain
    assert plain_one.index("2l") == plain_two.index("2l")


def test_agent_cells_depth_guides_and_clamp() -> None:
    assert rail_agent_cells(_agent(), _ctx(), depth=1).plain[0] == "└"
    two = rail_agent_cells(_agent(), _ctx(), depth=2)
    assert two.plain[:2] == "│└"
    three = rail_agent_cells(_agent(), _ctx(), depth=3)
    assert three.plain[:3] == "││└"
    assert rail_agent_cells(_agent(), _ctx(), depth=4).plain == three.plain
    assert rail_agent_cells(_agent(), _ctx(), depth=5).plain == three.plain
    assert (
        rail_agent_cells(_agent(), _ctx(), depth=-1).plain
        == rail_agent_cells(_agent(), _ctx(), depth=0).plain
    )


def test_agent_cells_name_visible() -> None:
    cells = rail_agent_cells(_agent(agent_name="2l"), _ctx(), depth=0)
    assert "2l" in cells.plain
    assert cells.cell_len == RAIL_CONTENT_CELLS


def test_agent_cells_count_present_iff_folded_total() -> None:
    plain = _agent(agent_name="2l")
    assert "×" not in rail_agent_cells(plain, _ctx(), depth=0).plain
    folded = rail_agent_cells(plain, _ctx(folded_total=4), depth=0)
    assert "×4" in folded.plain
    assert folded.cell_len == RAIL_CONTENT_CELLS
    capped = rail_agent_cells(plain, _ctx(folded_total=150), depth=0)
    assert "×99" in capped.plain
    # Shared count column: count ends at cell 16, pip at cell 18.
    assert capped.plain.index("×99") == 14
    assert capped.plain[-1] in {" ", "•", "▪"}


def test_folded_session_container_regression_reads_four() -> None:
    session_child = _agent(agent_session="alpha", role_suffix="--code")
    session = _agent(
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
        plan_chain_root=True,
    )
    session.followup_agents = [session_child]
    assert session.is_agent_session_container_row
    cells = rail_agent_cells(session, _ctx(folded_total=4), depth=0)
    assert "×4" in cells.plain
    assert "×0" not in cells.plain
    assert " 0" not in cells.plain.replace("×0", "")


def test_folded_member_total_agrees_with_annotation() -> None:
    agent = _agent(agent_type=AgentType.WORKFLOW, raw_suffix="fold-parent")
    fold_counts = {"fold-parent": (3, 1)}
    visible: set[str] = set()
    assert folded_member_total(agent, fold_counts, visible) == 4
    assert compute_fold_annotation(agent, fold_counts, visible) == " ×4"
    unfolded = {"fold-parent"}
    assert folded_member_total(agent, fold_counts, unfolded) is None
    assert "×4 −1" in compute_fold_annotation(
        agent, fold_counts, unfolded
    ) or compute_fold_annotation(agent, fold_counts, unfolded) in {"", " ×4 −1"}
    # Anonymous single-child exception.
    anon = _agent(
        agent_type=AgentType.WORKFLOW,
        appears_as_agent=True,
        is_anonymous=True,
        raw_suffix="anon-parent",
    )
    assert folded_member_total(anon, {"anon-parent": (1, 0)}, set()) is None
    assert compute_fold_annotation(anon, {"anon-parent": (1, 0)}, set()) == ""


def test_rail_row_name_parity_with_expanded() -> None:
    from sase.ace.tui.models._agent_tree import agent_tree_title as _tree_title

    for agent in _kind_agents() + _bucket_agents():
        # Untitled turns carry identity on the right-hand annotation; give
        # nameless ones a name so parity is defined.
        if _tree_title(agent) is None and not (
            agent.presented_agent_name or agent.agent_name
        ):
            agent.agent_name = f"turn-{agent.monitor_id or agent.gate_id or 'x'}"
            agent.refresh_raw_presented_agent_name()
        name, _style = rail_row_name(agent)
        if not name:
            continue
        left, _suffix, _option_id = format_agent_option(
            agent, 0, is_selected=False, is_expanded=False
        )
        assert name in left.plain, (name, left.plain)


def test_rail_row_name_resolution() -> None:
    named = _agent(agent_type=AgentType.NAMED_PROC, proc_label="lint")
    name, _style = rail_row_name(named)
    assert name == "lint"
    child = _agent(
        parent_workflow="flow", step_type="python", agent_type=AgentType.WORKFLOW
    )
    child_name, _child_style = rail_row_name(child)
    assert child_name
    clan = _agent(is_clan_container=True, agent_clan="map")
    clan_name, clan_style = rail_row_name(clan)
    assert clan_name == "map"
    assert clan_style == "#D75FFF"
    session = _agent(
        agent_session="alpha",
        agent_session_role="root",
        role_suffix="--0",
        plan_chain_root=True,
    )
    session.followup_agents = [_agent(agent_session="alpha", role_suffix="--code")]
    assert session.is_agent_session_container_row
    session_name, session_style = rail_row_name(session)
    assert session_name
    assert session_style == "#00AFFF"


def test_relative_names() -> None:
    assert relative_agent_label("research.9.cld", "research.9") == ".cld"
    assert relative_agent_label("1h--plan", "1h") == "--plan"
    assert relative_agent_label("sase-10", "sase-1") == "sase-10"
    assert relative_agent_label("alpha.", "alpha") == "alpha."
    assert relative_agent_label("alpha--", "alpha") == "alpha--"
    assert relative_agent_label("alpha.cld", None) == "alpha.cld"
    # Rail cells use the anchor's full name.
    parent = _agent(agent_name="bob-cli-29")
    parent_name, _style = rail_row_name(parent)
    child = _agent(agent_name="bob-cli-29.1")
    cells = rail_agent_cells(child, _ctx(), depth=1, anchor_name=parent_name)
    assert ".1" in cells.plain
    assert "bob-cli-29.1" not in cells.plain


def test_elision_budget_tail_biased_and_cell_aware() -> None:
    assert rail_middle_elide("abc", 5) == "abc"
    assert rail_middle_elide("", 3) == ""
    assert rail_middle_elide("abcdef", 0) == ""
    elided = rail_middle_elide("sase-1aq.10.7.5.land", 10)
    assert cell_len(elided) <= 10
    assert "…" in elided
    assert elided.endswith("land") or "land" in elided
    wide = rail_middle_elide("研" * 10, 7)
    assert cell_len(wide) <= 7


def test_dimming_only_settled_and_read() -> None:
    assert rail_name_is_dimmed(_agent(status="DONE"), is_unread=False) is True
    assert rail_name_is_dimmed(_agent(status="DONE"), is_unread=True) is False
    assert rail_name_is_dimmed(_agent(status="STOPPED"), is_unread=True) is True
    assert rail_name_is_dimmed(_agent(status="STOPPED"), is_unread=False) is True
    assert rail_name_is_dimmed(_agent(status="RUNNING"), is_unread=False) is False
    assert rail_name_is_dimmed(_agent(status="FAILED"), is_unread=False) is False


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


def test_banner_prefix_registers() -> None:
    agents = [_agent()]
    standard_l0 = rail_banner_cells(_group(level=0), agents)
    assert standard_l0.plain[0] == "▌"
    middle = rail_banner_cells(_group(level=1, key=("b", "sub")), agents)
    assert middle.plain[0] == "▎"
    name_root = rail_banner_cells(_group(level=2, key=("b", "sub", "leaf")), agents)
    assert name_root.plain[0] == "▸"
    for bucket, (glyph, _style) in RAIL_BUCKET_GLYPHS.items():
        group = _group(level=0, key=(bucket,), collapsed=False)
        cells = rail_banner_cells(group, agents, mode=GroupingMode.BY_STATUS)
        assert cells.plain[0] == glyph, bucket
        machine = _group(level=1, key=("here", bucket), collapsed=False)
        mid = rail_banner_cells(machine, agents, mode=GroupingMode.BY_MACHINE)
        assert "▎" in mid.plain and glyph in mid.plain, bucket
    by_date = rail_banner_cells(
        _group(level=0, key=("2026-09-28",)), agents, mode=GroupingMode.BY_DATE
    )
    assert by_date.cell_len == RAIL_CONTENT_CELLS
    hinted = rail_banner_cells(
        _group(level=0, key=("2026-09-28",)),
        agents,
        mode=GroupingMode.BY_DATE,
        hint="q",
    )
    assert hinted.plain[0] == "q"


def test_banner_cells_folded_layout() -> None:
    agents = [_agent(), _agent(status="FAILED"), _agent(status="DONE")]
    group = GroupRow(
        level=0,
        group_key=("proj",),
        agent_indices=(0, 1, 2),
        is_collapsed=True,
    )
    cells = rail_banner_cells(group, agents)
    assert "×3" in cells.plain
    assert "▸" not in cells.plain
    assert cells.plain[-1] == "✗"
    assert cells.cell_len == RAIL_CONTENT_CELLS


def test_banner_rule_at_least_one_cell_with_maximal_label() -> None:
    agents = [_agent()]
    group = _group(level=0, key=("x" * 60,), collapsed=False)
    cells = rail_banner_cells(group, agents)
    assert cells.cell_len == RAIL_CONTENT_CELLS
    assert "━" in cells.plain or "─" in cells.plain
    folded = rail_banner_cells(_group(level=0, key=("y" * 60,), collapsed=True), agents)
    assert folded.cell_len == RAIL_CONTENT_CELLS
    assert "━" in folded.plain or "─" in folded.plain


def test_rail_urgency_precedence() -> None:
    stopped = _agent(status="QUESTION")
    failed = _agent(status="FAILED")
    done = _agent(status="DONE")
    assert _rail_urgency([stopped, failed], []).plain == "?"
    assert _rail_urgency([failed, done], []).plain == "✗"
    assert _rail_urgency([done], [done.identity]).plain == "•"
    assert _rail_urgency([done], []).plain == " "
    assert _rail_urgency([], []).plain == " "


def test_panel_title_width_and_drop_order() -> None:
    from sase.ace.tui.actions.agents._display_panel_titles import AgentPanelCounts

    counts = AgentPanelCounts(lane_count=14, failed=1, unread=2)
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
    assert "@" in title.plain
    assert "×14" in title.plain
    # Wide emoji icons are dropped, not used as initials.
    emoji = rail_panel_title(key="agents", icon="🤖x", color="#00FF00")
    assert emoji.cell_len <= RAIL_TITLE_CELLS
    assert "🤖" not in emoji.plain
    # Merged panel shows All agents.
    merged = rail_panel_title(key="agents", merged=True)
    assert merged.plain == "All agents"
    # Selected focus marker.
    assert rail_panel_title(key="agents", selected=True).plain.startswith("❖")
    # Collapsed marker.
    assert rail_panel_title(key="agents", collapsed=True).plain[0] == "▸"
    # Long labels elide but hint and roll-up survive.
    long_name = rail_panel_title(
        key="a-very-long-tribe-name",
        hint="xy",
        selected=True,
        collapsed=True,
        counts=AgentPanelCounts(lane_count=3, failed=1),
    )
    assert long_name.cell_len <= RAIL_TITLE_CELLS
    assert "xy" in long_name.plain
    assert "✗" in long_name.plain


def test_overflow_subtitle() -> None:
    assert rail_overflow_subtitle(0, 0).plain == ""
    assert rail_overflow_subtitle(3, 0).plain == "▴3"
    assert rail_overflow_subtitle(0, 12).plain == "▾12"
    assert rail_overflow_subtitle(12, 3).plain == "▴12 ▾3"
    degraded = rail_overflow_subtitle(123456789, 987654321)
    assert degraded.cell_len <= RAIL_TITLE_CELLS


def test_tooltip_text() -> None:
    assert rail_tooltip_text(Text("")) is None
    assert rail_tooltip_text(Text("   ")) is None
    assert rail_tooltip_text(Text("name (RUNNING)      2 running")).plain == (
        "name (RUNNING)  2 running"
    )


def test_legend_entries() -> None:
    plains = [glyph.plain for glyph, _meaning in RAIL_LEGEND]
    assert "×N" in plains
    assert ".x" in plains
    assert any(meaning == "done and read (dim name)" for _glyph, meaning in RAIL_LEGEND)
    for glyph, meaning in RAIL_LEGEND:
        assert glyph.cell_len <= 2
        assert meaning.strip()


def test_rail_glyphs_single_cell_and_banned() -> None:
    texts = [Text(glyph, style=style) for glyph, style in RAIL_BUCKET_GLYPHS.values()]
    texts += [
        glyph for glyph, _meaning in RAIL_LEGEND if glyph.plain not in {"×N", ".x"}
    ]
    for agent in _bucket_agents() + _kind_agents():
        texts.append(rail_agent_cells(agent, _ctx(), depth=0))
        texts.append(rail_agent_cells(agent, _ctx(hint_char="ab"), depth=3))
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
    plain = _agent()
    assert row_kind_glyph(plain) is None
    assert "[agent]" in append_agent_row_prefix(plain, is_selected=False).plain
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


def test_hidden_retry_workflow_row_keeps_pre_epic_badge_order() -> None:
    """The top-level type badge (``≡``) renders after the hidden icon and
    retry badge, not before them — a 55e4bf73b regression."""
    workflow = _agent(
        agent_type=AgentType.WORKFLOW,
        appears_as_agent=True,
        is_anonymous=True,
        hidden=True,
        retry_attempt=1,
    )
    prefix = append_agent_row_prefix(
        workflow, is_selected=False, is_expanded=True
    ).plain
    assert prefix == "  ↳ ◌ ↻1 ≡ demo"

    machine_workflow = _agent(
        agent_type=AgentType.WORKFLOW,
        appears_as_agent=True,
        is_anonymous=True,
        hidden=True,
        retry_attempt=1,
        fleet_origin_alias="mac",
    )
    machine_prefix = append_agent_row_prefix(
        machine_workflow,
        is_selected=False,
        is_expanded=True,
        show_machine_chip=True,
    ).plain
    assert machine_prefix == "  ↳ ◌ ↻1 mac ≡ demo"


@pytest.mark.parametrize("bucket", list(RAIL_BUCKET_GLYPHS))
def test_banner_glyph_matches_rail_glyph(bucket: str) -> None:
    """Each expanded BY_STATUS L0 banner's leading glyph and style equal
    the rail glyph and style for that bucket."""
    glyph, style = RAIL_BUCKET_GLYPHS[bucket]
    group = GroupRow(level=0, group_key=(bucket,), agent_indices=())
    option = format_banner_option(
        group, [], width=40, sequence=0, mode=GroupingMode.BY_STATUS
    )
    text = option.prompt
    assert text.plain[0] == glyph  # type: ignore[union-attr]
    lead_spans = [s for s in text.spans if s.start <= 0 < s.end]  # type: ignore[union-attr]
    assert any(s.style == style for s in lead_spans), lead_spans
