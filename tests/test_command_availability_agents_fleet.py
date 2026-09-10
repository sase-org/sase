"""Agent tab command availability for fleet and remote rows."""

from __future__ import annotations

from sase.ace.tui.commands import (
    CommandContext,
    is_command_available,
)
from sase.ace.tui.models.agent import Agent, AgentType
from tests._command_availability_helpers import catalog_by_id as _catalog_by_id


def test_fleet_commands_are_contextual_for_remote_rows() -> None:
    catalog = _catalog_by_id()
    remote = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fleet-ui",
        project_file="/fleet/apollo/project.yml",
        status="RUNNING",
        start_time=None,
        agent_name="apollo.agent",
        fleet_origin_alias="apollo",
        fleet_logical_locator={
            "schema_version": 1,
            "project": "sase",
            "agent_id": "apollo.agent",
        },
        fleet_followed=True,
        fleet_capabilities={
            "resource": ["lifecycle.stop", "lifecycle.retry", "lifecycle.fork"]
        },
        fleet_row_revision={
            "schema_version": 1,
            "logical_key": "k",
            "revision": 1,
        },
        fleet_content={"handles": [{"id": "ch1"}]},
    )
    ctx = CommandContext(
        tab="agents",
        agent=remote,
        fleet_enabled=True,
        selected_agent_remote=True,
    )

    assert is_command_available(catalog["app.connect_agent_machine"], ctx)
    assert is_command_available(catalog["app.retry_remote_agent"], ctx)
    assert is_command_available(catalog["app.view_remote_agent_content"], ctx)
    assert is_command_available(catalog["app.run_workflow"], ctx)
    assert is_command_available(catalog["app.edit_hooks"], ctx)
    assert is_command_available(catalog["app.edit_spec"], ctx)


def test_removed_focus_fleet_commands_are_not_registered() -> None:
    catalog = _catalog_by_id()
    assert "app.cycle_agents_subtab" not in catalog
    assert "app.cycle_agents_subtab_reverse" not in catalog
    assert "app.toggle_agent_follow" not in catalog
    assert "app.view_agent_in_focus" not in catalog


def test_answer_remote_attention_requires_pending_entry() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.answer_remote_attention"]
    pending_question = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fleet-ui",
        project_file="/fleet/apollo/project.yml",
        status="QUESTION",
        start_time=None,
        agent_name="apollo.agent",
        fleet_origin_alias="apollo",
        fleet_capabilities={"resource": ["attention.answer_question"]},
        fleet_attention={
            "kind": "question",
            "state": "pending",
            "request_key": {"request_id": "question-0001"},
        },
    )
    ctx = CommandContext(
        tab="agents",
        agent=pending_question,
        fleet_enabled=True,
        selected_agent_remote=True,
    )
    assert is_command_available(spec, ctx)
    assert is_command_available(catalog["app.accept_proposal"], ctx)

    settled = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fleet-ui",
        project_file="/fleet/apollo/project.yml",
        status="RUNNING",
        start_time=None,
        agent_name="apollo.agent",
        fleet_origin_alias="apollo",
        fleet_capabilities={"resource": ["attention.answer_question"]},
        fleet_attention={
            "kind": "question",
            "state": "settled",
            "request_key": {"request_id": "question-0001"},
        },
    )
    settled_ctx = CommandContext(
        tab="agents",
        agent=settled,
        fleet_enabled=True,
        selected_agent_remote=True,
    )
    assert not is_command_available(spec, settled_ctx)


def test_remote_rows_hide_local_agent_actions() -> None:
    catalog = _catalog_by_id()
    remote = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fleet-ui",
        project_file="/fleet/apollo/project.yml",
        status="RUNNING",
        start_time=None,
        agent_name="apollo.agent",
        response_path="/tmp/remote-response.md",
        workspace_num=7,
        fleet_origin_alias="apollo",
        fleet_logical_locator={"schema_version": 1, "agent_id": "apollo.agent"},
        fleet_capabilities={
            "resource": ["lifecycle.stop", "lifecycle.retry", "lifecycle.fork"]
        },
    )
    ctx = CommandContext(
        tab="agents",
        agent=remote,
        fleet_enabled=True,
        selected_agent_remote=True,
    )

    assert is_command_available(catalog["app.kill_agent"], ctx)
    assert is_command_available(catalog["app.edit_hooks"], ctx)
    assert is_command_available(catalog["app.run_workflow"], ctx)
    assert not is_command_available(catalog["app.edit_spec"], ctx)
    assert not is_command_available(catalog["app.accept_proposal"], ctx)
    for command_id in {
        "app.open_tmux",
        "app.open_artifact_files",
        "app.jump_to_agent_patch",
        "copy.agents.chat",
        "copy.agents.file_path",
        "leader.revert_agent",
    }:
        assert not is_command_available(catalog[command_id], ctx), command_id


def test_setup_agent_machine_is_the_zero_machine_escape_hatch() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.setup_agent_machine"]

    # With no machine enrolled the unified list has no remote rows, so the
    # command menu must offer the enrollment guidance route.
    assert is_command_available(
        spec,
        CommandContext(tab="agents", agent=None, fleet_enabled=False),
    )
    # Once a machine is enrolled the per-row status command takes over.
    assert not is_command_available(
        spec,
        CommandContext(tab="agents", agent=None, fleet_enabled=True),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="patches", agent=None, fleet_enabled=False),
    )
