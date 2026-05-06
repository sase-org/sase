"""Tests for grouped banner emission in the Agents tab list."""

from __future__ import annotations

from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList

from ._agent_list_grouping_helpers import BR, make_agent


def test_main_panel_emits_project_and_changespec_banners() -> None:
    """A project banner + ChangeSpec banner precede every agent on the main panel."""
    widget = AgentList()
    widget.update_list([make_agent()], current_idx=0)
    assert widget._row_entries == [BR, BR, (0, None)]


def test_two_agents_with_distinct_projects_get_two_project_banners() -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="demo-a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="demo-b", project_file="/r/projB/proj.gp"),
        ],
        current_idx=0,
    )
    # projA: project banner + changespec banner + agent
    # spacer
    # projB: project banner + changespec banner + agent
    assert widget._row_entries == [
        BR,
        BR,
        (0, None),
        BR,
        BR,
        BR,
        (1, None),
    ]


def test_singleton_name_root_emits_no_deepest_banner_in_main_panel() -> None:
    """A lone dotted-name agent renders project + changespec banners only."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="demo", agent_name="coder.claude")],
        current_idx=0,
    )
    assert widget._row_entries == [BR, BR, (0, None)]


def test_named_agents_share_name_root_banner() -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="demo", agent_name="coder.claude"),
            make_agent(cl_name="demo", agent_name="coder.codex"),
        ],
        current_idx=0,
    )
    # Project + changespec + name-root banners, then the two agent rows.
    assert widget._row_entries == [BR, BR, BR, (0, None), (1, None)]


def test_banner_options_are_disabled() -> None:
    """Banner Options are disabled so OptionList cursor navigation skips them."""
    widget = AgentList()
    widget.update_list([make_agent()], current_idx=0)
    # First two Options are project + changespec banners; agent row is third.
    options = list(widget._options)
    assert options[0].disabled is True
    assert options[1].disabled is True
    assert options[2].disabled is False


def test_banner_label_renders_separately_for_project_and_changespec() -> None:
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="fix-bug-id", project_file="/repo/sase_100/proj.gp")],
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
            make_agent(cl_name="a"),
            make_agent(cl_name="b"),
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
            make_agent(cl_name="a", project_file="/r/projA/proj.gp"),
            make_agent(cl_name="b", project_file="/r/projB/proj.gp"),
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
    widget.update_list([make_agent(cl_name="")], current_idx=0)
    # Just the project banner + agent — no ChangeSpec banner inserted.
    assert widget._row_entries == [BR, (0, None)]


def test_no_changespec_panel_label_omits_changespec_suffix() -> None:
    """The level-0 banner label is the project name only — no ``/`` separator."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="", project_file="/repo/sase_100/proj.gp")],
        current_idx=0,
    )
    options = list(widget._options)
    plain_proj = options[0].prompt.plain  # type: ignore[union-attr]
    assert "sase_100" in plain_proj
    assert " / " not in plain_proj


def test_project_scoped_agent_renders_single_project_banner() -> None:
    """A project-scoped agent's cl_name must not become a duplicate L1 banner."""
    widget = AgentList()
    widget.update_list(
        [make_agent(cl_name="home", project_file="/repo/home/home.gp")],
        current_idx=0,
    )
    assert widget._row_entries == [BR, (0, None)]
    options = list(widget._options)
    plain_proj = options[0].prompt.plain  # type: ignore[union-attr]
    assert "home" in plain_proj
    assert len(options) == 2


def test_mixed_project_scoped_agent_uses_no_changespec_bucket() -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="fix-bug-id", project_file="/repo/home/home.gp"),
            make_agent(cl_name="home", project_file="/repo/home/home.gp"),
        ],
        current_idx=0,
    )
    options = list(widget._options)
    plains = [option.prompt.plain for option in options]  # type: ignore[union-attr]
    assert widget._row_entries == [BR, BR, (0, None), BR, (1, None)]
    assert "fix-bug-id" in plains[1]
    assert "(no ChangeSpec)" in plains[3]


def test_by_status_parent_marker_renders_inside_prefix_group() -> None:
    widget = AgentList()
    widget.update_list(
        [
            make_agent(cl_name="", agent_name="sase-42.3.1", status="DONE"),
            make_agent(cl_name="", agent_name="sase-42.3", status="DONE"),
            make_agent(cl_name="", agent_name="sase-42.3.2", status="DONE"),
        ],
        current_idx=0,
        grouping_mode=GroupingMode.BY_STATUS,
    )

    assert widget._row_entries == [
        BR,
        BR,
        BR,
        (1, None),
        (0, None),
        (2, None),
    ]
    options = list(widget._options)
    prefix_plain = options[2].prompt.plain  # type: ignore[union-attr]
    first_agent_plain = options[3].prompt.plain  # type: ignore[union-attr]
    assert "sase-42.3 " in prefix_plain
    assert "sase-42.3" in first_agent_plain
