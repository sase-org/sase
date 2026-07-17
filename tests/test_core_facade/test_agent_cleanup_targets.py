"""Tests for agent cleanup target conversion."""

from __future__ import annotations

from sase.core.agent_cleanup_facade import agent_to_cleanup_target
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire

from tests.test_core_facade._agent_cleanup_helpers import _agent, _STOP


def test_agent_to_cleanup_target_converts_current_agent_shape() -> None:
    agent = _agent(
        cl_name="convert",
        status="FAILED",
        pid=None,
        raw_suffix="20260430090102",
        tag="triage",
        agent_name="friendly",
        agent_family_parallel=True,
        stop_time=_STOP,
    )

    target = agent_to_cleanup_target(agent)

    assert target.identity == AgentCleanupIdentityWire(
        agent_type="run",
        cl_name="convert",
        raw_suffix="20260430090102",
    )
    assert target.status == "FAILED"
    assert target.workspace == 7
    assert target.from_changespec is False
    assert target.tag == "triage"
    assert target.agent_name == "friendly"
    assert target.agent_family_parallel is True
    assert target.display_name == "convert"
    assert target.start_time == "2026-04-30T09:00:00"
    assert target.stop_time == "2026-04-30T09:05:00"
