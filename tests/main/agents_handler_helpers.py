from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

from sase.agent.running import RunningAgentInfo


def running_info(**overrides: Any) -> RunningAgentInfo:
    """Build a RunningAgentInfo with sensible defaults for tests."""
    defaults: dict[str, Any] = {
        "name": "brisk-otter",
        "project": "sase",
        "pid": 12345,
        "model": "claude-opus-4.7",
        "provider": "claude",
        "workspace_num": 3,
        "duration": "1h12m",
        "approve": False,
        "prompt": "Fix the bug where X breaks under Y",
        "status": "RUNNING",
        "started_at": datetime(2026, 4, 23, 12, 34, 56, tzinfo=UTC),
        "duration_seconds": 4321,
        "artifacts_dir": "/home/bryan/.sase/projects/sase/artifacts/ace-run/20260423123456",
    }
    defaults.update(overrides)
    return RunningAgentInfo(**defaults)


def status_args(**overrides: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "all": False,
        "json": False,
        "project": None,
        "no_daemon": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class FakeDaemonTransport:
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
            return daemon_response(
                "capabilities",
                {"schema_version": 1, "capabilities": self.capabilities},
            )
        if payload["type"] == "read":
            surface = payload["data"]["surface"]
            return daemon_response(
                "read",
                {"surface": surface, "data": self.reads[surface].pop(0)},
            )
        raise AssertionError(f"unexpected fake daemon request: {payload['type']}")


def daemon_response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req-test",
        "payload": {"type": payload_type, "data": data},
    }


def agent_page(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
        "page": {"schema_version": 1, "next_cursor": None},
        "entries": {"schema_version": 1, "entries": entries},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1048576,
            "truncated": False,
        },
    }


def agent_detail(summary: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-1"},
        "summary": summary,
        "children": [],
        "artifacts": [],
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1048576,
            "truncated": False,
        },
        **extra,
    }


def agent_summary(**overrides: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": 1,
        "agent_id": "agent:sase:20260423123456",
        "project_id": "sase",
        "project_name": "sase",
        "project_dir": "/home/bryan/.sase/projects/sase",
        "project_file": "/home/bryan/.sase/projects/sase/sase.gp",
        "workflow_dir_name": "ace-run",
        "artifact_dir": (
            "/home/bryan/.sase/projects/sase/artifacts/ace-run/20260423123456"
        ),
        "timestamp": "20260423123456",
        "status": "running",
        "agent_type": "agent",
        "agent_name": "brisk-otter",
        "model": "claude-opus-4.7",
        "llm_provider": "claude",
        "started_at": "2026-04-23T12:34:56+00:00",
        "finished_at": None,
        "hidden": False,
        "has_done_marker": False,
        "has_running_marker": True,
        "has_waiting_marker": False,
        "has_workflow_state": False,
        "last_seq": 7,
        "pid": 12345,
        "workspace_num": 3,
        "approve": False,
        "prompt_snippet": "Fix the bug where X breaks under Y",
    }
    summary.update(overrides)
    return summary
