from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "rust_daemon_epic1" / "sources"


class FakeDaemonTransport:
    def __init__(
        self,
        *,
        capabilities: list[str] | None = None,
        reads: dict[str, list[dict[str, Any]]] | None = None,
        read_errors: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.capabilities = capabilities or []
        self.reads = reads or {}
        self.read_errors = read_errors or {}
        self.requests: list[dict[str, Any]] = []

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        payload = envelope["payload"]
        self.requests.append(payload)
        payload_type = payload["type"]
        if payload_type == "capabilities":
            return _response(
                "capabilities", {"schema_version": 1, "capabilities": self.capabilities}
            )
        if payload_type == "read":
            surface = payload["data"]["surface"]
            if surface in self.read_errors:
                return _error_response(self.read_errors[surface])
            data = self.reads[surface].pop(0)
            return _response("read", {"surface": surface, "data": data})
        raise AssertionError(f"unexpected fake daemon request: {payload_type}")


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
        "details": {"capability": "notifications.read"},
        "fallback": {"available": True, "reason": code, "message": "use direct"},
    }


def _notification_page(
    notifications: list[dict[str, Any]],
    *,
    next_cursor: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-notifications"},
        "page": {"schema_version": 1, "next_cursor": next_cursor},
        "notifications": notifications,
        "counts": {"total": len(notifications)},
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _bead_page(issues: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "snapshot": {"schema_version": 1, "snapshot_id": "snap-beads"},
        "page": {"schema_version": 1, "next_cursor": None},
        "issues": issues,
        "bounded": {
            "schema_version": 1,
            "max_payload_bytes": 1_048_576,
            "truncated": False,
        },
    }


def _issue_wire(issue: Any) -> dict[str, Any]:
    data = dataclasses.asdict(issue)
    data["status"] = issue.status.value
    data["issue_type"] = issue.issue_type.value
    data["tier"] = None if issue.tier is None else issue.tier.value
    return data
