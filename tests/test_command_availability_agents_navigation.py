"""Agent tab command availability for navigation and bulk commands."""

from __future__ import annotations

from sase.ace.tui.commands import (
    CommandContext,
    is_command_available,
)
from tests._command_availability_helpers import (
    catalog_by_id as _catalog_by_id,
    make_agent as _make_agent,
    make_patch as _make_patch,
)


def test_open_artifact_files_is_available_on_agents_tab() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.open_artifact_files"]
    assert is_command_available(spec, CommandContext(tab="agents"))
    assert not is_command_available(
        spec, CommandContext(tab="changespecs")
    )  # legacy tab id


def test_save_marked_agent_group_requires_marks_on_agents_tab() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.save_marked_agents"]

    assert not is_command_available(spec, CommandContext(tab="agents", mark_count=0))
    assert is_command_available(spec, CommandContext(tab="agents", mark_count=2))


def test_bulk_change_status_is_patch_only() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.bulk_change_status"]

    assert not is_command_available(spec, CommandContext(tab="agents", mark_count=2))
    assert is_command_available(
        spec,
        CommandContext(
            tab="changespecs",  # legacy tab id
            patch=_make_patch(),
            mark_count=2,
        ),
    )


def test_jump_to_agent_patch_requires_resolution() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.jump_to_agent_patch"]
    agent = _make_agent()
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_patch=False),
    )
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_patch=True),
    )


def test_open_tmux_requires_workspace() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.open_tmux"]
    no_ws = _make_agent(workspace_num=0)
    with_ws = _make_agent(workspace_num=42)
    assert not is_command_available(spec, CommandContext(tab="agents", agent=no_ws))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_ws))


def test_agent_cleanup_panel_visible_without_agent_context() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.open_agent_cleanup_panel"]
    assert is_command_available(spec, CommandContext(tab="agents"))
    assert is_command_available(
        spec, CommandContext(tab="agents", completed_agent_count=2)
    )


def test_jump_to_next_unread_done_agent_requires_unread_completed_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.jump_to_next_unread_done_agent"]
    assert not is_command_available(
        spec, CommandContext(tab="agents", unread_completed_agent_count=0)
    )
    assert is_command_available(
        spec, CommandContext(tab="agents", unread_completed_agent_count=1)
    )
    assert not is_command_available(
        spec,
        CommandContext(
            tab="changespecs", unread_completed_agent_count=1
        ),  # legacy tab id
    )


def test_revert_agent_available_with_marks_or_revertable_focus() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.revert_agent"]
    running = _make_agent(status="RUNNING")
    done = _make_agent(status="DONE")

    # No marks: needs a focused revertable agent.
    assert not is_command_available(spec, CommandContext(tab="agents", agent=running))
    assert is_command_available(spec, CommandContext(tab="agents", agent=done))

    # Marks present: runnable even when the focused row is non-revertable or
    # there is no focused agent at all (group banner).
    assert is_command_available(
        spec, CommandContext(tab="agents", agent=running, mark_count=2)
    )
    assert is_command_available(spec, CommandContext(tab="agents", mark_count=2))

    # Tab scoping still applies: marks on the Patches tab don't surface it.
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", mark_count=2),  # legacy tab id
    )


def test_jump_to_next_stopped_agent_requires_stopped_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["leader.jump_to_next_stopped_agent"]
    assert not is_command_available(
        spec, CommandContext(tab="agents", stopped_agent_count=0)
    )
    assert is_command_available(
        spec, CommandContext(tab="agents", stopped_agent_count=1)
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="changespecs", stopped_agent_count=1),  # legacy tab id
    )
