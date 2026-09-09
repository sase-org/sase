"""Agent tab command availability for kill and panel focus predicates."""

from __future__ import annotations

from sase.ace.tui.commands import (
    CommandContext,
    is_command_available,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests._command_availability_helpers import (
    catalog_by_id as _catalog_by_id,
    make_agent as _make_agent,
)


def test_kill_marked_and_edit_command_is_retired() -> None:
    catalog = _catalog_by_id()
    # The standalone ,X command no longer exists; ,x owns the behavior.
    assert "leader.kill_marked_and_edit" not in catalog


def test_kill_and_edit_is_contextual_on_marks_or_focus() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.kill_and_edit"]
    agent = _make_agent(status="RUNNING")
    # No marks but a focused agent: runnable on the focused row.
    assert is_command_available(
        spec, CommandContext(tab="agents", agent=agent, mark_count=0)
    )
    # Marks present: runnable even when the focused row is a group banner.
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=None, group_focused=True, mark_count=2),
    )
    # No marks and no focused agent: nothing to act on.
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=None, mark_count=0)
    )


def test_kill_and_edit_last_tracks_live_launch_record_independent_of_focus() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.kill_and_edit_last"]

    # A live launch record makes it runnable even with no focused agent and
    # no marks (,X ignores both).
    assert is_command_available(
        spec,
        CommandContext(
            tab="agents", agent=None, mark_count=0, has_live_launch_record=True
        ),
    )
    agent = _make_agent(status="RUNNING")
    assert is_command_available(
        spec,
        CommandContext(
            tab="agents",
            agent=agent,
            mark_count=3,
            has_live_launch_record=True,
        ),
    )
    # No live launch record: nothing to target, regardless of focus/marks.
    assert not is_command_available(
        spec,
        CommandContext(
            tab="agents", agent=agent, mark_count=0, has_live_launch_record=False
        ),
    )


def test_kill_agent_visible_on_group_banner_even_without_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    ctx = CommandContext(tab="agents", agent=None, group_focused=True)
    assert is_command_available(spec, ctx)


def test_collapsed_panel_exposes_kill_but_hides_hidden_agent_commands() -> None:
    catalog = _catalog_by_id()
    ctx = CommandContext(
        tab="agents",
        agent=None,
        collapsed_panel_focused=True,
    )

    assert is_command_available(catalog["app.kill_agent"], ctx)
    for command_id in {
        "app.run_workflow",
        "app.edit_spec",
        "app.edit_hooks",
        "app.rename_cl",
        "app.edit_agent_tribe",
        "app.open_tmux",
        "app.start_tmux_mode",
        "app.edit_panel",
        "app.open_artifact_files",
        "app.toggle_mark",
        "app.start_sibling_mode",
        "leader.agent_from_cl",
        "copy.agents.name",
    }:
        assert not is_command_available(catalog[command_id], ctx), command_id


def test_expanded_panel_exposes_kill_but_hides_remembered_agent_commands() -> None:
    catalog = _catalog_by_id()
    ctx = CommandContext(
        tab="agents",
        agent=None,
        panel_focused=True,
        panel_collapsed=False,
    )

    assert is_command_available(catalog["app.kill_agent"], ctx)
    for command_id in {
        "app.run_workflow",
        "app.edit_spec",
        "app.open_tmux",
        "app.toggle_mark",
        "copy.agents.name",
    }:
        assert not is_command_available(catalog[command_id], ctx), command_id


def test_zoom_panel_available_for_agent_or_whole_panel_focus_only() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.zoom_panel"]

    assert is_command_available(spec, CommandContext(tab="agents", agent=_make_agent()))
    assert is_command_available(spec, CommandContext(tab="agents", panel_focused=True))
    assert is_command_available(
        spec, CommandContext(tab="agents", collapsed_panel_focused=True)
    )
    assert not is_command_available(spec, CommandContext(tab="agents"))
    assert not is_command_available(
        spec, CommandContext(tab="agents", group_focused=True)
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", agent=_make_agent()),  # legacy tab id
    )


def test_isolate_panels_available_only_with_two_or_more_split_panels() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.isolate_panels"]

    assert is_command_available(spec, CommandContext(tab="agents", split_panel_count=2))
    assert not is_command_available(
        spec, CommandContext(tab="agents", split_panel_count=1)
    )
    assert not is_command_available(
        spec, CommandContext(tab="agents", split_panel_count=0)
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", split_panel_count=2),  # legacy tab id
    )


def test_collapse_panel_folds_available_for_agent_or_whole_panel_focus_only() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.collapse_panel_folds"]

    assert is_command_available(spec, CommandContext(tab="agents", agent=_make_agent()))
    assert is_command_available(spec, CommandContext(tab="agents", panel_focused=True))
    assert is_command_available(
        spec, CommandContext(tab="agents", collapsed_panel_focused=True)
    )
    assert not is_command_available(spec, CommandContext(tab="agents"))
    assert not is_command_available(
        spec, CommandContext(tab="agents", group_focused=True)
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", agent=_make_agent()),  # legacy tab id
    )


def test_collapse_all_panel_folds_available_regardless_of_focus() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.collapse_all_panel_folds"]

    assert is_command_available(spec, CommandContext(tab="agents"))
    assert is_command_available(spec, CommandContext(tab="agents", agent=_make_agent()))
    assert is_command_available(spec, CommandContext(tab="agents", panel_focused=True))
    assert is_command_available(spec, CommandContext(tab="agents", group_focused=True))
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", agent=_make_agent()),  # legacy tab id
    )


def test_kill_agent_hidden_when_no_agent_no_group_no_marks() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    ctx = CommandContext(tab="agents", agent=None)
    assert not is_command_available(spec, ctx)


def test_kill_agent_available_for_terminal_proc_shell() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    agent = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status="DONE",
        start_time=None,
        raw_suffix="abc123def456",
        proc_id="abc123def456",
        proc_status="success",
        proc_label="unit-1",
    )
    assert is_command_available(spec, CommandContext(tab="agents", agent=agent))
