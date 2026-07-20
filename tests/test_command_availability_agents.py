"""Command palette applicability predicates for the Agents tab."""

from __future__ import annotations

from sase.ace.tui.commands import (
    CommandContext,
    is_command_available,
)
from tests._command_availability_helpers import (
    catalog_by_id as _catalog_by_id,
    make_agent as _make_agent,
    make_changespec as _make_changespec,
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


def test_kill_agent_hidden_when_no_agent_no_group_no_marks() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    ctx = CommandContext(tab="agents", agent=None)
    assert not is_command_available(spec, ctx)


def test_edit_spec_for_resumable_done_agent_or_marks() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_spec"]
    done = _make_agent(status="DONE")
    plan_done = _make_agent(status="PLAN DONE")
    tale_done = _make_agent(status="TALE DONE")
    failed = _make_agent(status="FAILED")
    running = _make_agent(status="RUNNING")
    assert is_command_available(spec, CommandContext(tab="agents", agent=done))
    assert is_command_available(spec, CommandContext(tab="agents", agent=plan_done))
    assert is_command_available(spec, CommandContext(tab="agents", agent=tale_done))
    # FAILED agents don't get edit_chat (per footer logic)
    assert not is_command_available(spec, CommandContext(tab="agents", agent=failed))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=running))
    assert is_command_available(
        spec, CommandContext(tab="agents", agent=running, mark_count=2)
    )
    assert is_command_available(spec, CommandContext(tab="agents", mark_count=2))


def test_run_workflow_on_agents_requires_focused_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.run_workflow"]
    with_path = _make_agent(status="DONE", response_path="/tmp/r.txt")
    assert not is_command_available(spec, CommandContext(tab="agents", agent=None))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_path))


def test_edit_hooks_fork_requires_response_path_for_done_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    no_path = _make_agent(status="DONE", response_path=None)
    with_path = _make_agent(status="DONE", response_path="/tmp/r.txt")
    assert not is_command_available(spec, CommandContext(tab="agents", agent=no_path))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_path))


def test_edit_hooks_fork_allows_tale_done_with_response_path() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    no_path = _make_agent(status="TALE DONE", response_path=None)
    with_path = _make_agent(status="TALE DONE", response_path="/tmp/r.txt")
    assert not is_command_available(spec, CommandContext(tab="agents", agent=no_path))
    assert is_command_available(spec, CommandContext(tab="agents", agent=with_path))


def test_edit_hooks_fork_allows_named_clan_container() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    clan = _make_agent(status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "builders"

    assert is_command_available(spec, CommandContext(tab="agents", agent=clan))
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=clan, group_focused=True),
    )


def test_edit_hooks_fork_allows_only_named_tribe_panel_focus() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]

    for collapsed in (False, True):
        assert is_command_available(
            spec,
            CommandContext(
                tab="agents",
                agent=None,
                panel_focused=True,
                panel_collapsed=collapsed,
                focused_panel_key="builders",
            ),
        )
    assert not is_command_available(
        spec,
        CommandContext(
            tab="agents",
            agent=None,
            panel_focused=True,
            focused_panel_key=None,
        ),
    )


def test_wait_command_allows_agent_family_clan_tribe_and_marks() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.add_tag"]
    agent = _make_agent(status="RUNNING")
    agent.agent_name = "worker"
    family = _make_agent(status="DONE")
    family.agent_name = "builders-plan"
    family.agent_family = "builders"
    family.agent_family_role = "root"
    family.plan_chain_root = True
    clan = _make_agent(status="RUNNING")
    clan.is_clan_container = True
    clan.agent_clan = "builders"

    assert is_command_available(spec, CommandContext(tab="agents", agent=agent))
    assert is_command_available(spec, CommandContext(tab="agents", agent=family))
    assert is_command_available(spec, CommandContext(tab="agents", agent=clan))
    for collapsed in (False, True):
        assert is_command_available(
            spec,
            CommandContext(
                tab="agents",
                panel_focused=True,
                panel_collapsed=collapsed,
                focused_panel_key="builders",
            ),
        )
    assert is_command_available(
        spec,
        CommandContext(
            tab="agents",
            group_focused=True,
            mark_count=2,
        ),
    )


def test_wait_command_rejects_default_panel_group_banner_and_unnamed_agent() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.add_tag"]
    unnamed = _make_agent(status="RUNNING")

    assert not is_command_available(
        spec,
        CommandContext(
            tab="agents",
            panel_focused=True,
            focused_panel_key=None,
        ),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", group_focused=True),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=unnamed),
    )


def test_accept_proposal_on_agents_only_for_active_statuses() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.accept_proposal"]
    starting = _make_agent(status="STARTING")
    waiting = _make_agent(status="WAITING INPUT")
    done = _make_agent(status="DONE")
    assert is_command_available(spec, CommandContext(tab="agents", agent=starting))
    assert is_command_available(spec, CommandContext(tab="agents", agent=waiting))
    assert not is_command_available(spec, CommandContext(tab="agents", agent=done))


def test_toggle_attempt_view_requires_history_and_no_pin() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.toggle_attempt_view"]
    no_history = _make_agent(attempt_history=[])
    fake_attempt = object()
    with_history = _make_agent(attempt_history=[fake_attempt])  # type: ignore[arg-type]
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=no_history)
    )
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=with_history, attempt_pinned=False),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=with_history, attempt_pinned=True),
    )


def test_open_artifact_files_is_available_on_agents_tab() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.open_artifact_files"]
    assert is_command_available(spec, CommandContext(tab="agents"))
    assert not is_command_available(spec, CommandContext(tab="changespecs"))


def test_save_marked_agent_group_requires_marks_on_agents_tab() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.save_marked_agents"]

    assert not is_command_available(spec, CommandContext(tab="agents", mark_count=0))
    assert is_command_available(spec, CommandContext(tab="agents", mark_count=2))


def test_bulk_change_status_is_changespec_only() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.bulk_change_status"]

    assert not is_command_available(spec, CommandContext(tab="agents", mark_count=2))
    assert is_command_available(
        spec,
        CommandContext(
            tab="changespecs",
            changespec=_make_changespec(),
            mark_count=2,
        ),
    )


def test_jump_to_agent_changespec_requires_resolution() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.jump_to_agent_changespec"]
    agent = _make_agent()
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_changespec=False),
    )
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=agent, can_jump_to_changespec=True),
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
        CommandContext(tab="changespecs", unread_completed_agent_count=1),
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

    # Tab scoping still applies — marks on the ChangeSpecs tab don't surface it.
    assert not is_command_available(
        spec, CommandContext(tab="changespecs", mark_count=2)
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
        CommandContext(tab="changespecs", stopped_agent_count=1),
    )
