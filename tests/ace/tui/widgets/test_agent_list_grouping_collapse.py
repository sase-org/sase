"""Tests for collapsed-tree rendering and banner highlighting."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.widgets._agent_list_styling import (
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
)
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_list_grouping_helpers import BR, make_agent


def test_all_collapsed_renders_only_project_banners() -> None:
    """When every L0 is collapsed only project banners render."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    registry.collapse(("projB",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
    )
    # Two project banners separated by a single spacer row.
    assert all(entry == BR for entry in widget._row_entries)
    assert len(widget._row_entries) == 3


def test_collapsed_banner_is_selectable() -> None:
    """Collapsed-group banner Options are NOT disabled."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("repo",))
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="a")],
        current_idx=0,
        fold_registry=registry,
    )
    options = list(widget._options)
    assert options[0].disabled is False


def test_expanded_banner_stays_disabled_when_sibling_is_collapsed() -> None:
    """Mixed state: an expanded sibling banner remains non-selectable."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=1,
        fold_registry=registry,
    )
    # Layout: projA banner (collapsed, selectable), spacer, projB banner
    # (expanded, disabled), changespec banner, agent (b).
    options = list(widget._options)
    assert options[0].disabled is False  # collapsed projA banner
    assert options[2].disabled is True  # expanded projB banner


def test_resolve_row_returns_group_key_for_selectable_banner() -> None:
    """Banner clicks on a collapsed group carry the GroupRow key."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projA/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
    )
    # One project banner at row 0 covering both agents.
    agent_idx, attempt, group_key = widget._resolve_row(0)
    assert agent_idx == 0
    assert attempt is None
    assert group_key == ("projA",)


def test_current_group_key_drives_banner_highlight() -> None:
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    registry.collapse(("projB",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=1,
        fold_registry=registry,
        current_group_key=("projB",),
    )
    # Layout: projA banner (0), spacer (1), projB banner (2).
    assert widget.highlighted == 2


def test_changespec_banner_uses_distinct_accent_style() -> None:
    """The ChangeSpec banner gets its own bar+rule accent."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    cs_text = options[1].prompt
    cs_plain = cs_text.plain  # type: ignore[union-attr]
    assert "fix-bug-id" in cs_plain
    cs_styles = {s.style for s in cs_text.spans}  # type: ignore[union-attr]
    assert _CHANGESPEC_BANNER_BAR_STYLE in cs_styles
    assert _CHANGESPEC_BANNER_RULE_STYLE in cs_styles


def test_name_root_banner_label_uses_distinct_accent_style() -> None:
    """Name-root label gets its own accent style; branch/rule/chip stay dim."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="demo", agent_name="coder.claude"),
            make_agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Layout: project banner (0), changespec banner (1), name-root banner (2),
    # then the two agent rows.
    text = options[2].prompt
    plain = text.plain  # type: ignore[union-attr]
    # Branch glyph + label after the tier-guide gutter.
    assert "▸ coder " in plain

    spans_by_range = {(s.start, s.end): s.style for s in text.spans}  # type: ignore[union-attr]
    label_start = plain.index("coder")
    label_end = label_start + len("coder")
    # Only the label span should carry the label style.
    assert spans_by_range.get((label_start, label_end)) == _NAME_ROOT_BANNER_LABEL_STYLE

    # L0 banner: bar + label use the bar style; rule + chip use the
    # dimmer rule style.  L0 has no gutter so only those two styles
    # appear on its spans.
    proj_text = options[0].prompt
    proj_plain = proj_text.plain  # type: ignore[union-attr]
    assert proj_plain.startswith("▌ ")
    proj_spans = list(proj_text.spans)  # type: ignore[union-attr]
    bar_styles = {_PROJECT_BANNER_BAR_STYLE, _PROJECT_BANNER_RULE_STYLE}
    assert {s.style for s in proj_spans} <= bar_styles


def test_two_level_panel_name_root_banner_uses_indent() -> None:
    """In 2-level mode the name-root banner gets one project-tier guide segment."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="", agent_name="coder.claude"),
            make_agent(cl_name="", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Layout: project banner (0), name-root banner (1), then agents.
    text = options[1].prompt
    plain = text.plain  # type: ignore[union-attr]
    # One ``│  `` gutter segment (3 cells) for the project ancestor,
    # then the ``▸`` branch glyph and label — no second gutter segment
    # because there's no ChangeSpec tier in this panel.
    assert plain.startswith("│  ▸ coder ")
    spans = {s.style for s in text.spans}  # type: ignore[union-attr]
    assert _NAME_ROOT_BANNER_LABEL_STYLE in spans
    assert _NAME_ROOT_BANNER_BRANCH_STYLE in spans


def test_update_highlight_with_group_key_targets_banner_row() -> None:
    """``update_highlight(group_key=K)`` highlights the matching banner row."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    registry.collapse(("projB",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
        current_group_key=("projA",),
    )
    # Layout: projA banner (0), spacer (1), projB banner (2).
    assert widget.highlighted == 0
    widget.update_highlight(0, group_key=("projB",))
    assert widget.highlighted == 2


def test_update_highlight_falls_back_to_agent_search_when_group_key_unmatched() -> None:
    """No matching banner -> fall back to the agent-row search."""
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
    )
    # Layout: projA banner, changespec(a), agent0, spacer, projB banner,
    # changespec(b), agent1 → row 6.
    widget.update_highlight(1, group_key=("ghost",))
    assert widget.highlighted == 6


def test_banner_summary_chips_render_in_text() -> None:
    """Banner labels include the summary chip whether expanded or collapsed."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="shared", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="shared", project_file="/r/projA/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert "projA" in plain
    assert "2 agents" in plain
    assert "2 running" in plain
