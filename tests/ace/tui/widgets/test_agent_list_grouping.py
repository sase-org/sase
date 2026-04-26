"""Tests for grouped banner rendering in the Agents tab list."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.widgets._agent_list_styling import (
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
)
from sase.ace.tui.widgets.agent_list import _BANNER_ROW, AgentList

_BR = (_BANNER_ROW, None)


def _agent(
    *,
    cl_name: str = "demo",
    project_file: str = "/repo/proj.gp",
    tag: str | None = None,
    agent_name: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=agent_name,
        tag=tag,
    )


def test_main_panel_emits_project_and_changespec_banners() -> None:
    """A project banner + ChangeSpec banner precede every agent on the main panel."""
    widget = AgentList()
    widget.update_list([_agent()], current_idx=0)
    assert widget._row_entries == [_BR, _BR, (0, None)]


def test_two_agents_with_distinct_projects_get_two_project_banners() -> None:
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="demo-a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="demo-b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
    )
    # projA: project banner + changespec banner + agent
    # spacer
    # projB: project banner + changespec banner + agent
    assert widget._row_entries == [
        _BR,
        _BR,
        (0, None),
        _BR,
        _BR,
        _BR,
        (1, None),
    ]


def test_singleton_name_root_emits_no_deepest_banner_in_main_panel() -> None:
    """A lone dotted-name agent renders project + changespec banners only."""
    widget = AgentList()
    widget.update_list(
        [_agent(cl_name="demo", agent_name="coder.claude")],
        current_idx=0,
    )
    assert widget._row_entries == [_BR, _BR, (0, None)]


def test_named_agents_share_name_root_banner() -> None:
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    # Project + changespec + name-root banners, then the two agent rows.
    assert widget._row_entries == [_BR, _BR, _BR, (0, None), (1, None)]


def test_banner_options_are_disabled() -> None:
    """Banner Options are disabled so OptionList cursor navigation skips them."""
    widget = AgentList()
    widget.update_list([_agent()], current_idx=0)
    # First two Options are project + changespec banners; agent row is third.
    options = list(widget._options)
    assert options[0].disabled is True
    assert options[1].disabled is True
    assert options[2].disabled is False


def test_banner_label_renders_separately_for_project_and_changespec() -> None:
    widget = AgentList()
    widget.update_list(
        [_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    plain_proj = options[0].prompt.plain  # type: ignore[union-attr]
    plain_cs = options[1].prompt.plain  # type: ignore[union-attr]
    assert "sase_100" in plain_proj
    assert "fix-bug-id" not in plain_proj
    assert "fix-bug-id" in plain_cs


def test_resolve_row_routes_banner_clicks_to_first_agent() -> None:
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="a"),
            _agent(cl_name="b"),
        ],
        current_idx=0,
    )
    # Layout: project banner + changespec(a) banner + agent 0 + changespec(b) banner + agent 1
    assert widget._resolve_row(0) == (0, None, None)


def test_highlighted_row_skips_banner_offset() -> None:
    """Selecting an agent highlights the correct row even with banners ahead."""
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=1,
    )
    # Expected: projA banner, changespec(a) banner, agent 0, spacer,
    # projB banner, changespec(b) banner, agent 1 → highlight row 6.
    assert widget.highlighted == 6


# --- Two-level fallback (panel has no ChangeSpec) ---


def test_no_changespec_panel_renders_two_level_layout() -> None:
    """Regression guard: when no agent has a ChangeSpec, the UI matches today's."""
    widget = AgentList()
    widget.update_list([_agent(cl_name="")], current_idx=0)
    # Just the project banner + agent — no ChangeSpec banner inserted.
    assert widget._row_entries == [_BR, (0, None)]


def test_no_changespec_panel_label_omits_changespec_suffix() -> None:
    """The level-0 banner label is the project name only — no ``/`` separator."""
    widget = AgentList()
    widget.update_list(
        [_agent(cl_name="", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    plain_proj = options[0].prompt.plain  # type: ignore[union-attr]
    assert "sase_100" in plain_proj
    assert " / " not in plain_proj


# --- Collapsed-tree rendering ---


def test_all_collapsed_renders_only_project_banners() -> None:
    """When every L0 is collapsed only project banners render."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("projA",))
    registry.collapse(("projB",))
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
    )
    # Two project banners separated by a single spacer row.
    assert all(entry == _BR for entry in widget._row_entries)
    assert len(widget._row_entries) == 3


def test_collapsed_banner_is_selectable() -> None:
    """Collapsed-group banner Options are NOT disabled."""
    registry = AgentGroupFoldRegistry()
    registry.collapse(("repo",))
    widget = AgentList()
    widget.update_list(
        [_agent(cl_name="a")],
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
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
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
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projA/proj.gp"),
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
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
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
        [_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
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
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Layout: project banner (0), changespec banner (1), name-root banner (2),
    # then the two agent rows.
    text = options[2].prompt
    plain = text.plain  # type: ignore[union-attr]
    # Indented branch glyph + label.
    assert "╭─ coder " in plain

    spans_by_range = {(s.start, s.end): s.style for s in text.spans}  # type: ignore[union-attr]
    label_start = plain.index("coder")
    label_end = label_start + len("coder")
    # Only the label span should carry the label style.
    assert spans_by_range.get((label_start, label_end)) == _NAME_ROOT_BANNER_LABEL_STYLE

    # L0 banner: bar + label use the bar style; rule + chip use the
    # dimmer rule style.
    proj_text = options[0].prompt
    proj_plain = proj_text.plain  # type: ignore[union-attr]
    assert proj_plain.startswith("▌ ")
    proj_spans = list(proj_text.spans)  # type: ignore[union-attr]
    bar_styles = {_PROJECT_BANNER_BAR_STYLE, _PROJECT_BANNER_RULE_STYLE}
    assert {s.style for s in proj_spans} <= bar_styles


def test_two_level_panel_name_root_banner_uses_indent() -> None:
    """In 2-level mode the name-root banner uses the shallow indent."""
    widget = AgentList()
    widget.update_list(
        [
            _agent(cl_name="", agent_name="coder.claude"),
            _agent(cl_name="", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    # Layout: project banner (0), name-root banner (1), then agents.
    text = options[1].prompt
    plain = text.plain  # type: ignore[union-attr]
    # Two-space indent (NAME_ROOT_INDENT) — not the deep four-space variant.
    assert plain.startswith("  ╭─ coder ")
    assert not plain.startswith("    ")
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
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
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
            _agent(cl_name="a", project_file="/r/projA/proj.gp"),
            _agent(cl_name="b", project_file="/r/projB/proj.gp"),
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
            _agent(cl_name="shared", project_file="/r/projA/proj.gp"),
            _agent(cl_name="shared", project_file="/r/projA/proj.gp"),
        ],
        current_idx=0,
        fold_registry=registry,
    )
    options = list(widget._options)
    plain = options[0].prompt.plain  # type: ignore[union-attr]
    assert "projA" in plain
    assert "2 agents" in plain
    assert "2 running" in plain
