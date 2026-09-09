"""Agent tab command availability for local agent actions."""

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


def test_edit_hooks_fork_allows_failed_agent_without_response_path() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    failed = _make_agent(status="FAILED", response_path=None)
    failed.agent_name = "bad"

    assert is_command_available(spec, CommandContext(tab="agents", agent=failed))


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


def test_edit_hooks_fork_allows_proc_shell_with_proc_id() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    with_id = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status="RUNNING",
        start_time=None,
        raw_suffix="abc123def456",
        proc_id="abc123def456",
        proc_status="running",
    )
    without_id = Agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        project_file="",
        status="RUNNING",
        start_time=None,
        raw_suffix="abc123def456",
        proc_id=None,
        proc_status="running",
    )

    assert is_command_available(spec, CommandContext(tab="agents", agent=with_id))
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=without_id)
    )


def test_edit_hooks_fork_allows_monitor_with_monitor_id() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.edit_hooks"]
    with_id = _make_agent(status="MONITORING")
    with_id.agent_family_role = "monitor"
    with_id.role_suffix = "--mon"
    with_id.monitor_id = "m-123"
    without_id = _make_agent(status="MONITORING")
    without_id.agent_family_role = "monitor"
    without_id.role_suffix = "--mon"
    without_id.monitor_id = None

    assert is_command_available(spec, CommandContext(tab="agents", agent=with_id))
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=without_id)
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
