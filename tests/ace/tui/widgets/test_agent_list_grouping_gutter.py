"""Tests for the tier-guide gutter on banners and agent rows."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets._agent_list_styling import (
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
)
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_list_grouping_helpers import make_agent


def test_l0_banner_carries_no_tier_gutter() -> None:
    """Project banner is the top tier and renders flush at column 0."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    proj_plain = options[0].prompt.plain  # type: ignore[union-attr]
    # No leading ``│`` — the L0 banner anchors at the left edge.
    assert proj_plain.startswith("▌ ")


def test_changespec_banner_carries_one_project_gutter_segment() -> None:
    """L1 ChangeSpec banner threads a single project-blue gutter segment."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    cs_text = options[1].prompt
    cs_plain = cs_text.plain  # type: ignore[union-attr]
    # One ``│  `` segment (3 cells) before the ``▎`` ChangeSpec bar.
    assert cs_plain.startswith("│  ▎ ")
    cs_styles = {s.style for s in cs_text.spans}  # type: ignore[union-attr]
    assert _PROJECT_BANNER_RULE_STYLE in cs_styles


def test_changespec_banner_uses_light_rule() -> None:
    """L1 ChangeSpec rule is the light ``─`` so weight matches L2 name-roots."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    cs_plain = options[1].prompt.plain  # type: ignore[union-attr]
    assert "─" in cs_plain
    assert "━" not in cs_plain


def test_name_root_banner_in_3_level_carries_two_gutter_segments() -> None:
    """L2 name-root threads project + ChangeSpec gutter segments."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="fix-bug-id", agent_name="coder.claude"),
            make_agent(cl_name="fix-bug-id", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    nr_text = options[2].prompt
    nr_plain = nr_text.plain  # type: ignore[union-attr]
    assert nr_plain.startswith("│  │  ▸ coder ")
    nr_styles = {s.style for s in nr_text.spans}  # type: ignore[union-attr]
    assert _PROJECT_BANNER_RULE_STYLE in nr_styles
    assert _CHANGESPEC_BANNER_RULE_STYLE in nr_styles


def test_agent_row_under_3_level_carries_two_gutter_segments() -> None:
    """Agent rows beneath project + ChangeSpec carry both gutter segments."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="fix-bug-id", agent_name="coder.claude"),
            make_agent(cl_name="fix-bug-id", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Row order: L0, L1 cs, L2 name-root, agent0, agent1.
    agent_plain = options[3].prompt.plain  # type: ignore[union-attr]
    assert agent_plain.startswith("│  │  ")


def test_agent_row_under_2_level_carries_one_gutter_segment() -> None:
    """In 2-level STANDARD mode agent rows carry only the project segment."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="", agent_name="solo.runner")],
        current_idx=0,
    )
    options = list(widget._options)
    # Row order: L0 project banner, agent.
    agent_plain = options[1].prompt.plain  # type: ignore[union-attr]
    assert agent_plain.startswith("│  ")
    assert not agent_plain.startswith("│  │  ")


def test_agent_row_under_by_status_carries_one_bucket_gutter_segment() -> None:
    """BY_STATUS agents under a name-root sit under one bucket gutter segment."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="", agent_name="coder.claude", status="RUNNING"),
            make_agent(cl_name="", agent_name="coder.codex", status="RUNNING"),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )
    options = list(widget._options)
    # Row order: L0 bucket, L1 name-root, agent0, agent1.
    agent_plain = options[2].prompt.plain  # type: ignore[union-attr]
    assert agent_plain.startswith("│  ")
    assert not agent_plain.startswith("│  │  ")


def test_by_date_4hour_banner_uses_level2_visual_style() -> None:
    """BY_DATE 4-hour headings use the promoted L1/ChangeSpec register."""
    widget = AgentList()
    widget.update_list(
        [make_agent(start_time=datetime(2026, 4, 25, 9, 0, 0))],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=datetime(2026, 4, 25, 12, 0, 0),
    )
    options = list(widget._options)
    window_text = options[1].prompt
    window_plain = window_text.plain  # type: ignore[union-attr]
    assert window_plain.startswith("│  ▎ 8AM-12PM ")
    window_styles = {s.style for s in window_text.spans}  # type: ignore[union-attr]
    assert _PROJECT_BANNER_RULE_STYLE in window_styles
    assert _CHANGESPEC_BANNER_BAR_STYLE in window_styles
    assert _CHANGESPEC_BANNER_RULE_STYLE in window_styles


def test_by_date_hourly_banner_carries_bucket_and_window_gutters() -> None:
    """BY_DATE hourly headings sit under the date bucket and 4-hour window."""
    widget = AgentList()
    widget.update_list(
        [make_agent(start_time=datetime(2026, 4, 25, 9, 0, 0))],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=datetime(2026, 4, 25, 12, 0, 0),
    )
    options = list(widget._options)
    hourly_text = options[2].prompt
    hourly_plain = hourly_text.plain  # type: ignore[union-attr]
    assert hourly_plain.startswith("│  │  ▸ 09:00 ")
    hourly_styles = {s.style for s in hourly_text.spans}  # type: ignore[union-attr]
    assert _PROJECT_BANNER_RULE_STYLE in hourly_styles
    assert _CHANGESPEC_BANNER_RULE_STYLE in hourly_styles
    assert _NAME_ROOT_BANNER_BRANCH_STYLE in hourly_styles
    assert any(
        span.start == 3
        and span.end == 6
        and span.style == _CHANGESPEC_BANNER_RULE_STYLE
        for span in hourly_text.spans  # type: ignore[union-attr]
    )


def test_by_date_agent_row_carries_bucket_and_window_gutters() -> None:
    widget = AgentList()
    widget.update_list(
        [make_agent(start_time=datetime(2026, 4, 25, 9, 0, 0))],
        current_idx=0,
        grouping_mode=GroupingMode.BY_DATE,
        now=datetime(2026, 4, 25, 12, 0, 0),
    )
    options = list(widget._options)
    agent_plain = options[3].prompt.plain  # type: ignore[union-attr]
    assert agent_plain.startswith("│  │  ")
