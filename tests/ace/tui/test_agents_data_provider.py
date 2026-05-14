"""Tests for ACE Agents-tab data providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.data_providers import (
    _AgentsProviderSnapshot,
    _DaemonAgentsDataProvider,
    _apply_daemon_agent_events,
    agents_daemon_reads_enabled,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.daemon.client import LocalDaemonClient


class _FakeDaemonTransport:
    def __init__(
        self,
        *,
        capabilities: list[str],
        reads: dict[str, list[dict[str, Any]]],
    ) -> None:
        self.capabilities = capabilities
        self.reads = reads
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _daemon_response(
                "capabilities",
                {"schema_version": 1, "capabilities": self.capabilities},
            )
        if payload["type"] == "read":
            surface = payload["data"]["surface"]
            return _daemon_response(
                "read",
                {"surface": surface, "data": self.reads[surface].pop(0)},
            )
        raise AssertionError(f"unexpected daemon request: {payload['type']}")


class _StubDirectProvider:
    prefers_daemon = False

    def __init__(self) -> None:
        self.calls = 0

    def load_agents(
        self,
        *,
        changespec_snapshot: list[Any] | None = None,
        full_history: bool = False,
    ) -> _AgentsProviderSnapshot:
        del changespec_snapshot, full_history
        self.calls += 1
        return _AgentsProviderSnapshot(
            agents=[_agent(cl_name="fallback", raw_suffix="20260514110000")],
            workflow_agent_steps=[],
            load_state=_load_state("source_scan"),
            used_daemon=False,
        )


def _daemon_response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req-test",
        "payload": {"type": payload_type, "data": data},
    }


def _agent_page(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {"schema_version": 1, "entries": entries},
    }


def _agent_summary(**overrides: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": 1,
        "agent_id": "agent:demo:20260514100000",
        "project_id": "demo",
        "project_name": "demo",
        "project_dir": "/tmp/.sase/projects/demo",
        "project_file": "/tmp/.sase/projects/demo/demo.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/.sase/projects/demo/artifacts/ace-run/20260514100000",
        "timestamp": "20260514100000",
        "status": "running",
        "agent_type": "agent",
        "cl_name": "feature",
        "agent_name": "feature-agent",
        "model": "claude-opus-4.7",
        "llm_provider": "claude",
        "started_at": "2026-05-14T10:00:10Z",
        "finished_at": None,
        "hidden": False,
        "has_done_marker": False,
        "has_running_marker": True,
        "has_waiting_marker": False,
        "has_workflow_state": False,
        "last_seq": 7,
        "pid": 4242,
        "workspace_num": 3,
        "approve": True,
        "vcs_provider": "GitHub",
        "tag": "daemon",
    }
    summary.update(overrides)
    return summary


def _load_state(
    source: str,
) -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source=source,  # type: ignore[arg-type]
        used_artifact_index=False,
    )


def _agent(
    *,
    cl_name: str = "feature",
    raw_suffix: str = "20260514100000",
    status: str = "RUNNING",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/.sase/projects/demo/demo.sase",
        status=status,
        start_time=datetime(2026, 5, 14, 10, 0, 0),
        raw_suffix=raw_suffix,
    )


def test_daemon_agents_provider_loads_initial_snapshot_without_source_scan() -> None:
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_active": [_agent_page([_agent_summary()])],
            "agent_recent": [_agent_page([])],
        },
    )
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
    )

    with (
        patch("sase.ace.tui.models.agent_loader.load_tiered_agents") as load_tiered,
        patch("sase.ace.agent_tags.load_agent_tags", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set(), data_provider=provider)

    load_tiered.assert_not_called()
    assert len(result.all_agents) == 1
    agent = result.all_agents[0]
    assert agent.cl_name == "feature"
    assert agent.status == "RUNNING"
    assert agent.workspace_num == 3
    assert agent.agent_name == "feature-agent"
    assert agent.tag == "daemon"
    assert result.load_state.artifact_source == "daemon_projection"
    assert [
        request["data"]["surface"]
        for request in transport.requests
        if request["type"] == "read"
    ] == [
        "agent_active",
        "agent_recent",
    ]


def test_daemon_agents_provider_falls_back_when_capability_missing() -> None:
    transport = _FakeDaemonTransport(capabilities=[], reads={})
    direct = _StubDirectProvider()
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
        direct_provider=direct,
    )

    snapshot = provider.load_agents()

    assert direct.calls == 1
    assert snapshot.used_daemon is False
    assert snapshot.fallback_reason == "unsupported_capability"
    assert [agent.cl_name for agent in snapshot.agents] == ["fallback"]


def test_ace_agents_provider_honors_rollout_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_ACE_AGENTS_DAEMON_READS", raising=False)
    config = {"daemon": {"reads": {"surfaces": {"ace_agents": True}}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert agents_daemon_reads_enabled() is True


def test_ace_agents_provider_env_override_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_ACE_AGENTS_DAEMON_READS", "0")
    config = {"daemon": {"reads": {"surfaces": {"ace_agents": True}}}}

    with patch("sase.daemon.read_config.load_merged_config", return_value=config):
        assert agents_daemon_reads_enabled() is False


def test_daemon_agent_events_apply_upsert_delete_and_resync() -> None:
    base = _agent()
    upsert = {
        "events": [
            {
                "payload": {
                    "delta": {
                        "collection": "agents",
                        "handle": "agent:demo:20260514100100",
                        "operation": "upsert",
                        "fields": _agent_summary(
                            agent_id="agent:demo:20260514100100",
                            timestamp="20260514100100",
                            cl_name="new-feature",
                        ),
                    }
                }
            }
        ]
    }

    after_upsert = _apply_daemon_agent_events([base], upsert)

    assert after_upsert.resync_required is False
    assert {agent.raw_suffix for agent in after_upsert.agents} == {
        "20260514100000",
        "20260514100100",
    }

    delete = {
        "events": [
            {
                "payload": {
                    "delta": {
                        "collection": "agents",
                        "handle": "agent:demo:20260514100000",
                        "operation": "delete",
                        "fields": {},
                    }
                }
            }
        ]
    }
    after_delete = _apply_daemon_agent_events(after_upsert.agents, delete)

    assert [agent.raw_suffix for agent in after_delete.agents] == ["20260514100100"]

    resync = {
        "events": [{"payload": {"resync_required": {"reason": "snapshot_expired"}}}]
    }
    after_resync = _apply_daemon_agent_events(after_delete.agents, resync)

    assert after_resync.resync_required is True
    assert after_resync.resync_reason == "snapshot_expired"
