"""Shared helpers for sudo gate coverage."""

from __future__ import annotations

import shutil
from typing import Any


def _request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    return {
        "reason": "Need to refresh root-owned package metadata",
        "commands": [
            {
                "id": "refresh",
                "argv": [executable],
                "why": "Refresh package metadata",
            }
        ],
        "run_as": "root",
        "cwd": "/tmp",
        "env": {"LC_ALL": "C"},
        "timeout_seconds": 30,
        "stop_policy": "terminate",
        "output_policy": "bounded",
    }


def _multi_command_request() -> dict[str, Any]:
    executable = shutil.which("true")
    assert executable is not None
    request = _request()
    request["commands"] = [
        {"id": "alpha", "argv": [executable, "--alpha"], "why": "Run alpha"},
        {"id": "beta", "argv": [executable, "--beta"], "why": "Run beta"},
        {"id": "gamma", "argv": [executable, "--gamma"], "why": "Run gamma"},
    ]
    return request


def _runner_ledger(manifest: dict[str, Any], manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "completed",
        "entries": [
            {
                "id": command["id"],
                "status": "ran",
                "exit_code": 0,
                "duration_seconds": 0.0,
                "output_tail": "",
            }
            for command in manifest["commands"]
        ],
        "diagnostic": None,
    }


def _auth_failed_ledger(
    manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "auth_failed",
        "entries": [],
        "diagnostic": "authentication failed",
    }


def _runner_error_ledger(
    manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "request_id": manifest["request_id"],
        "manifest_sha256": manifest_sha256,
        "outcome": "runner_error",
        "entries": [
            {
                "id": command["id"],
                "status": "skipped",
                "exit_code": None,
                "duration_seconds": 0.0,
                "output_tail": "",
            }
            for command in manifest["commands"]
        ],
        "diagnostic": "failed to start sudo command in cwd /missing",
    }


def _runner_receipt(envelope: dict[str, Any]) -> dict[str, Any]:
    sudo_payload = envelope["payload"]["sudo"]
    manifest = sudo_payload["manifest"]
    return _runner_ledger(manifest, sudo_payload["manifest_sha256"])
