"""Tests for ACE Agents-tab data providers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.actions.agents._artifact_provider import read_agent_artifacts_for_tui
from sase.ace.tui.actions.agents._notification_provider import (
    read_notification_startup_for_tui,
)
from sase.ace.tui.actions.changespec._provider import read_changespecs_for_tui
from sase.ace.tui.data_providers import (
    AgentsViewport,
    _AgentsProviderSnapshot,
    _DaemonAgentsDataProvider,
    _apply_daemon_agent_events,
    _agent_snapshot,
    agents_daemon_reads_enabled,
    agent_row_handle,
    make_agents_data_provider,
)
from sase.ace.tui.provider_contract import SelectionGeneration
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.daemon.client import LocalDaemonClient


class _FakeDaemonTransport:
    def __init__(
        self,
        *,
        capabilities: list[str],
        reads: dict[str, list[dict[str, Any]]],
        read_errors: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.reads = reads
        self.read_errors = read_errors or {}
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
            if surface in self.read_errors:
                return _daemon_error_response(self.read_errors[surface])
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
        search_query: str | None = None,
        viewport: AgentsViewport | None = None,
    ) -> _AgentsProviderSnapshot:
        del changespec_snapshot, full_history, search_query, viewport
        self.calls += 1
        agents = [_agent(cl_name="fallback", raw_suffix="20260514110000")]
        return _AgentsProviderSnapshot(
            agents=agents,
            workflow_agent_steps=[],
            load_state=_load_state("source_scan"),
            shared_snapshot=_agent_snapshot(
                agents,
                provider_source="direct",
                prefers_daemon=False,
                fallback_reason=None,
                fallback_message=None,
                snapshot_id=None,
                page_count=1,
                full_reload=True,
            ),
            used_daemon=False,
        )


def _daemon_response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req-test",
        "payload": {"type": payload_type, "data": data},
    }


def _daemon_error_response(data: dict[str, Any]) -> dict[str, Any]:
    return _daemon_response("error", data)


def _agent_page(
    entries: list[dict[str, Any]], *, next_cursor: str | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
        "page": {"schema_version": 1, "next_cursor": next_cursor},
        "entries": {"schema_version": 1, "entries": entries},
    }


def _changespec_page() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-changespecs"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {
            "schema_version": 1,
            "entries": [
                {
                    "schema_version": 1,
                    "handle": "changespec:demo:feature",
                    "project_id": "demo",
                    "name": "feature",
                    "project_basename": "demo",
                    "file_path": "/tmp/.sase/projects/demo/demo.sase",
                    "source_path": "/tmp/.sase/projects/demo/demo.sase",
                    "is_archive": False,
                    "status": "WIP",
                    "parent": None,
                    "cl_or_pr": None,
                    "bug": None,
                    "updated_at": "2026-05-14T10:00:00Z",
                    "last_seq": 1,
                }
            ],
        },
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _notification_page() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-notifications"},
        "page": {"schema_version": 1, "next_cursor": None},
        "notifications": [],
        "counts": {"priority": 1, "errors": 0, "rest": 2, "muted": 3},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _rpc_error(code: str, message: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "code": code,
        "message": message or code.replace("_", " "),
        "retryable": False,
        "target": "payload",
        "details": {"capability": "agents.read"},
        "fallback": {"available": True, "reason": code, "message": "use direct"},
    }


def _agent_detail(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-detail"},
        "summary": _agent_summary(),
        "children": [],
        "artifacts": artifacts,
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
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


def test_daemon_agents_provider_loads_initial_snapshot_without_source_scan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"ace_agent_snapshot": [_agent_page([_agent_summary()])]},
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
    ] == ["ace_agent_snapshot"]
    provider_snapshot = result.provider_snapshot
    assert provider_snapshot is not None
    assert provider_snapshot.provider.source == "daemon"
    assert provider_snapshot.snapshot_id == "snap-1"
    assert provider_snapshot.metadata["page_count"] == 1
    assert provider_snapshot.metadata["full_reload"] is False
    assert provider_snapshot.metadata["surfaces"] == ["ace_agent_snapshot"]
    assert provider_snapshot.row_handles[0] == agent_row_handle(
        provider_snapshot.rows[0]
    )


def test_shared_startup_daemon_client_reuses_capability_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_NOTIFICATIONS_READS", "1")
    monkeypatch.setenv("SASE_DAEMON_ACE_CHANGESPECS_READS", "1")
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    transport = _FakeDaemonTransport(
        capabilities=["notifications.read", "changespecs.read", "agents.read"],
        reads={
            "notification_list": [_notification_page()],
            "changespec_list": [_changespec_page()],
            "ace_agent_snapshot": [_agent_page([_agent_summary()])],
        },
    )
    client = LocalDaemonClient(transport=transport)

    notifications = read_notification_startup_for_tui(client=client)
    changespecs = read_changespecs_for_tui(client=client)
    provider = make_agents_data_provider(client=client)
    with patch("sase.ace.agent_tags.load_agent_tags", return_value={}):
        agents = provider.load_agents()

    assert notifications.used_daemon is True
    assert changespecs.used_daemon is True
    assert agents.used_daemon is True
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "read",
        "read",
        "read",
    ]
    assert [
        request["data"]["surface"]
        for request in transport.requests
        if request["type"] == "read"
    ] == [
        "notification_list",
        "changespec_list",
        "ace_agent_snapshot",
    ]


def test_daemon_agents_provider_fetches_only_viewport_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "ace_agent_snapshot": [_agent_page([_agent_summary()], next_cursor="next")],
        },
    )
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
    )

    snapshot = provider.load_agents(
        viewport=AgentsViewport(visible_rows=5, prefetch_rows=7)
    )

    read_requests = [
        request["data"] for request in transport.requests if request["type"] == "read"
    ]
    assert [request["surface"] for request in read_requests] == [
        "ace_agent_snapshot",
    ]
    assert [request["data"]["page"]["limit"] for request in read_requests] == [12]
    assert snapshot.shared_snapshot.metadata["page_count"] == 1
    assert snapshot.shared_snapshot.first_page.next_cursor == "next"


def test_daemon_agents_provider_uses_project_loop_for_older_daemons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        read_errors={
            "ace_agent_snapshot": _rpc_error(
                "invalid_request",
                "unknown variant `ace_agent_snapshot`",
            )
        },
        reads={
            "agent_active": [_agent_page([_agent_summary()])],
            "agent_recent": [_agent_page([])],
        },
    )
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
    )

    snapshot = provider.load_agents()

    read_requests = [
        request["data"] for request in transport.requests if request["type"] == "read"
    ]
    assert [request["surface"] for request in read_requests] == [
        "ace_agent_snapshot",
        "agent_active",
        "agent_recent",
    ]
    assert snapshot.used_daemon is True
    assert snapshot.shared_snapshot.metadata["surfaces"] == [
        "agent_active",
        "agent_recent",
    ]


def test_daemon_agents_provider_uses_search_and_archive_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_ARCHIVE_SEARCH_READS", "1")
    search_transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "ace_agent_snapshot": [_agent_page([_agent_summary(cl_name="needle")])],
        },
    )
    search_provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=search_transport),
        project_ids=["demo"],
    )

    search_snapshot = search_provider.load_agents(search_query="needle")

    assert search_snapshot.agents[0].cl_name == "needle"
    search_reads = [
        request["data"]
        for request in search_transport.requests
        if request["type"] == "read"
    ]
    assert [request["surface"] for request in search_reads] == ["ace_agent_snapshot"]
    assert search_reads[0]["data"]["query"] == "needle"

    archive_transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"agent_archive": [_agent_page([_agent_summary(cl_name="old")])]},
    )
    archive_provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=archive_transport),
        project_ids=["demo"],
    )

    archive_snapshot = archive_provider.load_agents(full_history=True)

    assert archive_snapshot.agents[0].cl_name == "old"
    archive_reads = [
        request["data"]
        for request in archive_transport.requests
        if request["type"] == "read"
    ]
    assert [request["surface"] for request in archive_reads] == ["agent_archive"]


def test_agent_artifact_provider_uses_daemon_detail_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_ARTIFACTS_READS", "1")
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_detail": [
                _agent_detail(
                    [
                        {
                            "schema_version": 1,
                            "agent_id": "agent:demo:20260514100000",
                            "artifact_path": "/tmp/report.md",
                            "artifact_kind": "markdown",
                            "display_name": "Report",
                            "role": "explicit",
                        }
                    ]
                )
            ],
        },
    )
    agent = _agent()

    result = read_agent_artifacts_for_tui(
        agent,
        client=LocalDaemonClient(transport=transport),
    )

    assert result.used_daemon is True
    assert [
        (artifact.label, artifact.kind, artifact.path)
        for artifact in result.value.artifacts
    ] == [("Report", "markdown", "/tmp/report.md")]
    assert result.value.shared_snapshot is not None
    assert result.value.shared_snapshot.provider.source == "daemon"
    assert result.value.shared_snapshot.snapshot_id == "snap-detail"
    read_requests = [
        request for request in transport.requests if request["type"] == "read"
    ]
    assert [request["data"]["surface"] for request in read_requests] == ["agent_detail"]


def test_agent_artifact_provider_falls_back_when_ace_surface_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_ARTIFACTS_READS", "0")
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"agent_detail": [_agent_detail([])]},
    )

    result = read_agent_artifacts_for_tui(
        _agent(),
        client=LocalDaemonClient(transport=transport),
    )

    assert result.used_daemon is False
    assert result.surface == "ace_artifact_detail"
    assert result.fallback_reason == "surface_disabled"
    assert result.value.shared_snapshot is not None
    assert result.value.shared_snapshot.provider.source == "direct_fallback"
    assert transport.requests == []


def test_daemon_agents_provider_falls_back_when_capability_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
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
    assert snapshot.shared_snapshot.provider.fallback.reason == "unsupported_capability"
    assert [agent.cl_name for agent in snapshot.agents] == ["fallback"]


def test_daemon_agents_provider_falls_back_when_ace_surface_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "0")
    monkeypatch.delenv("SASE_ACE_AGENTS_DAEMON_READS", raising=False)
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={
            "agent_active": [_agent_page([_agent_summary()])],
            "agent_recent": [_agent_page([])],
        },
    )
    direct = _StubDirectProvider()
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
        direct_provider=direct,
    )

    snapshot = provider.load_agents()

    assert direct.calls == 1
    assert snapshot.used_daemon is False
    assert snapshot.fallback_reason == "surface_disabled"
    assert snapshot.shared_snapshot.provider.fallback.reason == "surface_disabled"
    assert transport.requests == []


def test_daemon_agents_provider_archive_search_has_independent_rollout_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_DAEMON_ACE_AGENTS_READS", "1")
    monkeypatch.setenv("SASE_DAEMON_ACE_ARCHIVE_SEARCH_READS", "0")
    monkeypatch.delenv("SASE_ACE_ARCHIVE_SEARCH_DAEMON_READS", raising=False)
    transport = _FakeDaemonTransport(
        capabilities=["agents.read"],
        reads={"agent_search": [_agent_page([_agent_summary(cl_name="needle")])]},
    )
    direct = _StubDirectProvider()
    provider = _DaemonAgentsDataProvider(
        client=LocalDaemonClient(transport=transport),
        project_ids=["demo"],
        direct_provider=direct,
    )

    snapshot = provider.load_agents(search_query="needle")

    assert direct.calls == 1
    assert snapshot.used_daemon is False
    assert snapshot.fallback_reason == "surface_disabled"
    assert snapshot.shared_snapshot.provider.fallback.message == (
        "daemon reads disabled for ace_archive_search"
    )
    assert transport.requests == []


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


def test_agent_row_handles_match_direct_and_daemon_logical_row() -> None:
    direct = _agent(raw_suffix="20260514100000")
    daemon = _agent(raw_suffix="20260514100000")

    assert agent_row_handle(direct).stable_id == agent_row_handle(daemon).stable_id


def test_selection_generation_ignores_stale_detail_requests() -> None:
    generation = SelectionGeneration()
    request = generation.request(agent_row_handle(_agent()))

    assert generation.accepts(request) is True
    generation.bump()
    assert generation.accepts(request) is False
