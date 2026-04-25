"""Tests for grouped banner rendering in the Agents tab list."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_styling import (
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAME_ROOT_BANNER_STYLE,
    _PROJECT_BANNER_STYLE,
    _TAG_BANNER_STYLE,
)
from sase.ace.tui.widgets.agent_list import _BANNER_ROW, AgentList

_BR = (_BANNER_ROW, None)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tags: tuple[str, ...] = (),
    agent_name: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=agent_name,
        tags=tags,
    )


def test_main_panel_emits_banner_rows() -> None:
    """Tag + project banners precede every agent on the main panel."""
    widget = AgentList(panel="main")
    widget.update_list([_agent()], current_idx=0)
    assert widget._row_entries == [_BR, _BR, (0, None)]


def test_pinned_panel_stays_flat() -> None:
    """The pinned panel skips banner rendering entirely (Phase 3 limitation)."""
    widget = AgentList(panel="pinned")
    widget.update_list([_agent(), _agent(cl_name="other")], current_idx=0)
    assert widget._row_entries == [(0, None), (1, None)]


def test_two_agents_with_distinct_tags_get_two_tag_banners() -> None:
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="demo-a", tags=("alpha",)),
            _agent(cl_name="demo-b", tags=("beta",)),
        ],
        current_idx=0,
    )
    # alpha tag banner + alpha project banner + agent 0 +
    # beta tag banner + beta project banner + agent 1
    assert widget._row_entries == [
        _BR,
        _BR,
        (0, None),
        _BR,
        _BR,
        (1, None),
    ]


def test_singleton_name_root_emits_no_level2_banner_in_main_panel() -> None:
    """A lone dotted-name agent renders only tag + project banners — no level-2 chrome."""
    widget = AgentList(panel="main")
    widget.update_list(
        [_agent(cl_name="demo", agent_name="coder.claude")],
        current_idx=0,
    )
    assert widget._row_entries == [_BR, _BR, (0, None)]


def test_named_agents_share_name_root_banner() -> None:
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    # Tag + project + name-root banners, then the two agent rows.
    assert widget._row_entries == [_BR, _BR, _BR, (0, None), (1, None)]


def test_banner_options_are_disabled() -> None:
    """Banner Options are disabled so OptionList cursor navigation skips them."""
    widget = AgentList(panel="main")
    widget.update_list([_agent()], current_idx=0)
    # First two Options are banners; the agent row is third.
    options = list(widget._options)  # internal OptionList list
    assert options[0].disabled is True
    assert options[1].disabled is True
    assert options[2].disabled is False


def test_banner_label_renders_in_option_text() -> None:
    widget = AgentList(panel="main")
    widget.update_list(
        [_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    plain_tag = options[0].prompt.plain  # type: ignore[union-attr]
    plain_proj = options[1].prompt.plain  # type: ignore[union-attr]
    assert "(untagged)" in plain_tag
    assert "sase_100 / fix-bug-id" in plain_proj


def test_resolve_row_routes_banner_clicks_to_first_agent() -> None:
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="a", tags=("alpha",)),
            _agent(cl_name="b", tags=("alpha",)),
        ],
        current_idx=0,
    )
    # Row layout: [tag_banner, project_a_banner, agent0, project_b_banner, agent1]
    # Banner at row 0 routes to agent at row 2 (index 0); group_key is None
    # because banners at fold level 3 are non-selectable.
    assert widget._resolve_row(0) == (0, None, None)
    assert widget._resolve_row(1) == (0, None, None)
    # Project banner before agent 1 routes forward to agent 1.
    assert widget._resolve_row(3) == (1, None, None)


def test_highlighted_row_skips_banner_offset() -> None:
    """Selecting an agent highlights the correct row even with banners ahead."""
    widget = AgentList(panel="main")
    widget.update_list(
        [_agent(cl_name="a"), _agent(cl_name="b")],
        current_idx=1,
        has_focus=True,
    )
    # Expected layout:
    #   0 = tag banner
    #   1 = project_a banner
    #   2 = agent 0
    #   3 = project_b banner
    #   4 = agent 1
    assert widget.highlighted == 4


# --- Phase 4: collapsed-tree rendering ---


def test_fold_level_0_renders_only_tag_banners() -> None:
    """At L0 the AgentList shows tag banners only — no agents, no projects."""
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="a", tags=("alpha",)),
            _agent(cl_name="b", tags=("beta",)),
        ],
        current_idx=0,
        group_fold_level=0,
    )
    # Only banner rows; no agent rows.
    assert all(entry == _BR for entry in widget._row_entries)
    assert len(widget._row_entries) == 2


def test_banners_are_selectable_when_fold_level_below_3() -> None:
    """At fold level < 3, banner Options are NOT disabled."""
    widget = AgentList(panel="main")
    widget.update_list(
        [_agent(cl_name="a", tags=("alpha",))],
        current_idx=0,
        group_fold_level=0,
    )
    options = list(widget._options)
    assert options[0].disabled is False


def test_resolve_row_returns_group_key_for_selectable_banner() -> None:
    """Banner clicks at fold level < 3 carry the GroupRow key for Phase 5."""
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="a", tags=("alpha",)),
            _agent(cl_name="b", tags=("alpha",)),
        ],
        current_idx=0,
        group_fold_level=0,
    )
    # One tag banner at row 0 covering both agents.
    agent_idx, attempt, group_key = widget._resolve_row(0)
    assert agent_idx == 0
    assert attempt is None
    assert group_key == ("alpha",)


def test_current_group_key_drives_banner_highlight() -> None:
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="a", tags=("alpha",)),
            _agent(cl_name="b", tags=("beta",)),
        ],
        current_idx=1,
        group_fold_level=0,
        current_group_key=("beta",),
        has_focus=True,
    )
    # Beta tag banner is the second banner row.
    assert widget.highlighted == 1


def test_name_root_banner_label_uses_distinct_accent_style() -> None:
    """L2 name-root label gets its own accent style; decorators/chip/padding stay dim."""
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Layout: tag banner (0), project banner (1), name-root banner (2),
    # then the two agent rows.
    text = options[2].prompt
    plain = text.plain  # type: ignore[union-attr]
    assert plain.startswith("· coder ·")

    spans_by_range = {(s.start, s.end): s.style for s in text.spans}  # type: ignore[union-attr]
    label_start = plain.index("coder")
    label_end = label_start + len("coder")
    assert spans_by_range[(0, label_start)] == _NAME_ROOT_BANNER_STYLE
    assert spans_by_range[(label_start, label_end)] == _NAME_ROOT_BANNER_LABEL_STYLE
    decor_right_end = label_end + len(" ·")
    assert spans_by_range[(label_end, decor_right_end)] == _NAME_ROOT_BANNER_STYLE
    # Every remaining span (chip + padding) keeps the dim style.
    for (start, _), style in spans_by_range.items():
        if start >= decor_right_end:
            assert style == _NAME_ROOT_BANNER_STYLE

    # L0 and L1 banners stay single-span at their existing accent styles.
    tag_text = options[0].prompt
    assert all(s.style == _TAG_BANNER_STYLE for s in tag_text.spans)  # type: ignore[union-attr]
    proj_text = options[1].prompt
    assert all(s.style == _PROJECT_BANNER_STYLE for s in proj_text.spans)  # type: ignore[union-attr]


def test_update_highlight_with_group_key_targets_banner_row() -> None:
    """``update_highlight(group_key=K)`` highlights the matching banner row.

    Regression: at fold level < 3 the j/k debounced refresh path needs to
    move the visible highlight onto a banner row, not stay on whichever
    row the previous full refresh chose.  ``current_idx`` should be
    irrelevant when ``group_key`` matches a banner.
    """
    widget = AgentList(panel="main")
    widget.update_list(
        [
            _agent(cl_name="a", tags=("alpha",)),
            _agent(cl_name="b", tags=("beta",)),
        ],
        current_idx=0,
        group_fold_level=0,
        current_group_key=("alpha",),
        has_focus=True,
    )
    # Sanity: starts on the alpha banner (row 0).
    assert widget.highlighted == 0
    # Move to the beta banner via the highlight-only path.
    widget.update_highlight(0, group_key=("beta",))
    assert widget.highlighted == 1


def test_update_highlight_falls_back_to_agent_search_when_group_key_unmatched() -> None:
    """No matching banner -> fall back to the agent-row search.

    Defensive: covers a refresh-vs-fold race where the caller's
    ``_current_group_key`` no longer matches any rendered banner.
    """
    widget = AgentList(panel="main")
    widget.update_list(
        [_agent(cl_name="a"), _agent(cl_name="b")],
        current_idx=0,
        has_focus=True,
    )
    # Layout: tag, project_a, agent0, project_b, agent1.
    widget.update_highlight(1, group_key=("ghost",))
    assert widget.highlighted == 4


def test_banner_summary_chips_render_in_text() -> None:
    """Banner labels at any fold level include the summary chip."""
    widget = AgentList(panel="main")
    a = _agent(cl_name="a", tags=("alpha",))
    a_running = a  # status defaults to RUNNING
    widget.update_list(
        [a_running, _agent(cl_name="b", tags=("alpha",))],
        current_idx=0,
        group_fold_level=0,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert "@alpha" in plain
    assert "2 agents" in plain
    assert "2 running" in plain
