"""Shared helpers for the ``test_agent_tree_clan_status*`` test modules.

Public helpers used by more than one ``test_agent_tree_clan_status_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option

__all__ = [
    "assert_turn_presentation_cleared",
    "format_member",
    "make_base_agent",
    "make_clan_member",
    "make_testing_member",
    "style_at",
]

_NOW = datetime(2026, 7, 17, 10, 5, 0)

_GENERATION = "20260717100000"


def _base_agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    step_type: str | None = None,
    hidden: bool = False,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
    tribe: str | None = None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/sase.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        run_start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type=step_type,
        is_hidden_step=hidden,
        agent_clan=clan,
        agent_clan_generation=generation,
        tribe=tribe,
        clan_tribe=clan_tribe,
        clan_summary=clan_summary,
    )


def make_base_agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    step_type: str | None = None,
    hidden: bool = False,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
    tribe: str | None = None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> Agent:
    """Build a base clan test agent (public alias of ``_base_agent``)."""
    return _base_agent(
        name,
        suffix,
        agent_type=agent_type,
        status=status,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type=step_type,
        hidden=hidden,
        clan=clan,
        generation=generation,
        tribe=tribe,
        clan_tribe=clan_tribe,
        clan_summary=clan_summary,
    )


def make_clan_member(
    name: str,
    suffix: str,
    *,
    status: str,
    status_bucket: str | None = None,
    monitor_start_status: str | None = None,
    monitor_stop_status: str | None = None,
    monitor_state: str | None = None,
    gate_start_status: str | None = None,
    gate_stop_status: str | None = None,
    gate_state: str | None = None,
    gate_accent: str | None = None,
    gate_execution_active: bool = False,
    gate_finalize_proc_id: str | None = None,
) -> Agent:
    """Build a clan member with turn-presentation fields set."""
    row = _base_agent(name, suffix, status=status)
    row.status_bucket = status_bucket
    row.monitor_start_status = monitor_start_status
    row.monitor_stop_status = monitor_stop_status
    row.monitor_state = monitor_state
    row.gate_start_status = gate_start_status
    row.gate_stop_status = gate_stop_status
    row.gate_state = gate_state
    row.gate_accent = gate_accent
    row.gate_execution_active = gate_execution_active
    row.gate_finalize_proc_id = gate_finalize_proc_id
    return row


def make_testing_member(suffix: str = "testing") -> Agent:
    """Build the lone TESTING member used across clan-status tests."""
    return make_clan_member(
        f"research.{suffix}",
        suffix,
        status="TESTING",
        status_bucket="Running",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="running",
    )


def style_at(text: Text, position: int) -> str | None:
    """Return the style covering ``position`` in ``text``."""
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def format_member(agent: Agent, index: int = 0) -> Text:
    """Format a clan member row for style/label assertions."""
    text, _, _ = format_agent_option(agent, index, is_selected=False, now=_NOW)
    return text


def assert_turn_presentation_cleared(agent: Agent) -> None:
    """Assert a clan container carries no turn-presentation fields."""
    assert agent.monitor_start_status is None
    assert agent.monitor_stop_status is None
    assert agent.monitor_state is None
    assert agent.gate_start_status is None
    assert agent.gate_stop_status is None
    assert agent.gate_state is None
    assert agent.gate_accent is None
    assert agent.gate_execution_active is False
    assert agent.gate_finalize_proc_id is None
