"""Tests for daemon scheduler lifecycle mutation helpers."""

from __future__ import annotations

from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.lifecycle_scheduler import (
    _LifecycleTarget,
    _scheduler_lifecycle_mode,
    submit_lifecycle_batch_if_enabled,
)


class _SchedulerTransport:
    def __init__(self, *, capabilities: list[str]) -> None:
        self.capabilities = capabilities
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _response(
                "capabilities",
                {"schema_version": 1, "capabilities": self.capabilities},
            )
        if payload["type"] == "scheduler_submit":
            data = payload["data"]
            return _response(
                "scheduler_submit",
                {
                    "schema_version": 1,
                    "handle": {
                        "schema_version": 1,
                        "batch_id": data["batch_id"],
                        "idempotency_key": data["idempotency_key"],
                        "queue_id": data["queue_id"],
                        "project_id": data["project_id"],
                        "slot_count": len(data["launch_specs"]),
                        "status": "queued",
                        "created_at": "2026-05-14T06:00:00Z",
                    },
                    "duplicate": False,
                    "status": {"schema_version": 1, "handle": {}, "slots": []},
                },
            )
        raise AssertionError(f"unexpected request: {payload['type']}")


def test_lifecycle_scheduler_mode_defaults_direct(monkeypatch) -> None:
    monkeypatch.delenv("SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE", raising=False)
    monkeypatch.delenv("SASE_SCHEDULER_LIFECYCLE_MODE", raising=False)

    assert _scheduler_lifecycle_mode() == "direct"


def test_lifecycle_batch_shadow_submits_one_slot_per_target(monkeypatch) -> None:
    monkeypatch.setenv("SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE", "shadow")
    transport = _SchedulerTransport(capabilities=["scheduler.submit"])
    client = LocalDaemonClient(transport=transport)

    result = submit_lifecycle_batch_if_enabled(
        [
            _LifecycleTarget(
                "kill",
                project_id="sase",
                name="alpha",
                raw_suffix="20260514010101",
                pid=123,
            ),
            _LifecycleTarget(
                "kill",
                project_id="sase",
                name="beta",
                raw_suffix="20260514010202",
                pid=456,
            ),
        ],
        client=client,
    )

    assert result.submitted is True
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "scheduler_submit",
    ]
    submit = transport.requests[-1]["data"]
    assert submit["queue_id"] == "agent-lifecycle"
    assert submit["metadata"] == {
        "scheduler_task_kind": "agent_lifecycle",
        "operation": "bulk_kill",
        "target_count": 2,
    }
    assert len(submit["launch_specs"]) == 2
    assert submit["launch_specs"][0]["metadata"]["operation"] == "kill"
    assert submit["launch_specs"][0]["metadata"]["target"]["name"] == "alpha"
    assert submit["launch_specs"][1]["metadata"]["target"]["pid"] == 456


def test_lifecycle_batch_falls_back_without_scheduler_capability(monkeypatch) -> None:
    monkeypatch.setenv("SASE_DAEMON_SCHEDULER_LIFECYCLE_MODE", "daemon")
    transport = _SchedulerTransport(capabilities=[])
    client = LocalDaemonClient(transport=transport)

    result = submit_lifecycle_batch_if_enabled(
        [_LifecycleTarget("dismiss", project_id="sase", raw_suffix="ts1")],
        client=client,
    )

    assert result.submitted is False
    assert result.mode == "daemon"
    assert result.fallback_reason == "unsupported_capability"
    assert [request["type"] for request in transport.requests] == ["capabilities"]


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
    }
