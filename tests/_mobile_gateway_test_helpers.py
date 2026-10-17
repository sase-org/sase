"""Shared helpers for the private mobile gateway test modules."""

from __future__ import annotations

import argparse
import json
from typing import Any


def make_args(**overrides: Any) -> argparse.Namespace:
    values = {
        "bind_address": None,
        "port": None,
        "state_dir": None,
        "allow_non_loopback": False,
        "gateway_command": None,
        "agent_bridge_command": None,
        "helper_bridge_command": None,
        "push_provider": None,
        "fcm_project_id": None,
        "fcm_service_account_json": None,
        "fcm_credential_env": None,
        "fcm_dry_run": False,
        "push_timeout_seconds": None,
        "push_retry_limit": None,
        "startup_timeout": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


OWNER_LOCAL_HEALTH = {
    "status": "ok",
    "pairing": {"issuance": "owner_local_v1"},
}
ISSUED_PAIRING = {
    "schema_version": 1,
    "pairing_id": "pair_123",
    "code": "123456",
    "expires_at": "2026-05-06T15:00:00Z",
    "host_label": "workstation",
    "host_fingerprint": None,
}


def capture_issue(captured: list[dict[str, Any]]) -> Any:
    def issue(request: dict[str, Any]) -> dict[str, Any]:
        captured.append(request)
        return dict(ISSUED_PAIRING)

    return issue
