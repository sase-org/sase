"""Tests for local daemon write scaffolding and fallback routing."""

from __future__ import annotations

from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.write_facade import write_or_fallback
from sase.notifications.daemon_writes import apply_notification_state_update


class FakeDaemonTransport:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        write_errors: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.capabilities = capabilities or []
        self.write_errors = write_errors or {}
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        if payload["type"] == "capabilities":
            return _response(
                "capabilities", {"schema_version": 1, "capabilities": self.capabilities}
            )
        if payload["type"] == "write":
            surface = payload["data"]["surface"]
            if surface in self.write_errors:
                return _error_response(self.write_errors[surface])
            return _response(
                "write",
                {
                    "schema_version": 1,
                    "surface": surface,
                    "outcome": {
                        "schema_version": 1,
                        "event_seq": 1,
                        "event_type": "test.changed",
                        "duplicate": False,
                        "changed": True,
                        "resource_handle": "test:1",
                        "source_exports": [],
                        "projection_snapshot": {
                            "outcome": {
                                "schema_version": 1,
                                "matched_count": 1,
                                "changed_count": 1,
                                "appended_count": 0,
                                "rewritten": True,
                                "notifications": [
                                    {
                                        "id": "n1",
                                        "timestamp": "2026-05-14T00:00:00+00:00",
                                        "sender": "test",
                                        "notes": [],
                                        "files": [],
                                        "action": None,
                                        "action_data": {},
                                        "read": True,
                                        "dismissed": False,
                                        "silent": False,
                                        "muted": False,
                                        "snooze_until": None,
                                    }
                                ],
                                "counts": {},
                                "expired_ids": [],
                                "stats": {},
                            }
                        },
                    },
                    "fallback": {"available": False, "reason": None, "message": None},
                },
            )
        raise AssertionError(f"unexpected fake daemon request: {payload['type']}")


def test_write_client_emits_contract_shape() -> None:
    transport = FakeDaemonTransport()
    client = LocalDaemonClient(transport=transport)

    result = client.write(
        "contract",
        {
            "schema_version": 1,
            "project_id": "project-a",
            "idempotency_key": "key-1",
            "actor": {
                "schema_version": 1,
                "actor_type": "test",
                "name": "pytest",
            },
            "payload": {"ok": True},
        },
    )

    assert result["surface"] == "contract"
    assert transport.requests[-1] == {
        "type": "write",
        "data": {
            "surface": "contract",
            "schema_version": 1,
            "project_id": "project-a",
            "idempotency_key": "key-1",
            "actor": {
                "schema_version": 1,
                "actor_type": "test",
                "name": "pytest",
            },
            "payload": {"ok": True},
        },
    }


def test_write_or_fallback_uses_direct_writer_for_unsupported_mutation() -> None:
    transport = FakeDaemonTransport(
        capabilities=["writes.contract"],
        write_errors={"contract": _rpc_error("unsupported_mutation")},
    )
    client = LocalDaemonClient(transport=transport)

    result = write_or_fallback(
        "contract",
        client=client,
        daemon_writer=lambda daemon: daemon.write(
            "contract",
            {
                "schema_version": 1,
                "project_id": "project-a",
                "idempotency_key": "key-1",
                "actor": {
                    "schema_version": 1,
                    "actor_type": "test",
                    "name": "pytest",
                },
                "payload": {},
            },
        ),
        direct_writer=lambda: "direct",
    )

    assert result.value == "direct"
    assert not result.used_daemon
    assert result.fallback_reason == "unsupported_mutation"


def test_write_or_fallback_checks_capability_before_routing() -> None:
    transport = FakeDaemonTransport(capabilities=[])
    client = LocalDaemonClient(transport=transport)

    result = write_or_fallback(
        "contract",
        client=client,
        daemon_writer=lambda _daemon: "daemon",
        direct_writer=lambda: "direct",
    )

    assert result.value == "direct"
    assert not result.used_daemon
    assert result.fallback_reason == "unsupported_capability"
    assert [request["type"] for request in transport.requests] == ["capabilities"]


def test_notification_state_update_uses_notifications_write_capability() -> None:
    transport = FakeDaemonTransport(capabilities=["notifications.write"])
    client = LocalDaemonClient(transport=transport)

    result = apply_notification_state_update(
        {"kind": "mark_read", "id": "n1"},
        client=client,
        direct_writer=lambda: "direct",
    )

    assert result.used_daemon
    assert result.value.matched_count == 1
    assert result.value.notifications[0].read is True
    assert [request["type"] for request in transport.requests] == [
        "capabilities",
        "write",
    ]
    assert transport.requests[-1]["data"]["surface"] == "notifications.state_update"


def _response(payload_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": payload_type, "data": data},
    }


def _error_response(error: dict[str, Any]) -> dict[str, Any]:
    return _response("error", error)


def _rpc_error(code: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "code": code,
        "message": code.replace("_", " "),
        "retryable": False,
        "target": "payload",
        "details": {"capability": "contract.write"},
        "fallback": {"available": True, "reason": code, "message": "use direct"},
    }
