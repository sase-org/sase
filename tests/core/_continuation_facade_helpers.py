"""Shared test fixtures for continuation facade tests."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from sase.core.continuation_facade import (
    bind_conditional_completion,
    seal_conditional_completion,
)
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    continuation_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding

_SHA = "a" * 64


def call_continuation_binding(name: str, payload: Any) -> dict[str, Any]:
    value = require_rust_binding(name)(continuation_wire_to_json_dict(payload))
    if not isinstance(value, dict):
        raise TypeError(f"{name} returned non-dict payload")
    return dict(value)


def make_owner() -> dict[str, str]:
    return {
        "project": "sase",
        "run_id": "run-1",
        "agent_name": "agent-1",
        "machine_name": "athena",
    }


def make_node(
    node_id: str,
    parents: list[str] | None = None,
    *,
    kind: str = "agent_delta",
) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": kind,
        "parent_ids": parents or [],
        "owner": make_owner(),
        "content_ref": f"file:explicit:{node_id}",
        "content_sha256": _SHA,
    }


def make_monitor_result(
    outcome: str = "failed",
    *,
    exit_code: int | None = 1,
) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "result_id": "result-1",
        "monitor_id": "monitor-1",
        "starter_execution_id": "run-1",
        "outcome": outcome,
        "exit_code": exit_code,
        "command": ["just", "check"],
        "cwd": "/workspace/sase",
        "started_at": "2026-09-11T12:00:00Z",
        "ended_at": "2026-09-11T12:01:00Z",
        "elapsed_ms": 60_000,
        "workspace_identity": "workspace-1",
        "diagnostic_manifest_ref": "file:explicit:diagnostics",
        "retained_log": {
            "log_ref": "file:explicit:monitor-log",
            "local_locator": "logs/monitor.log",
            "total_observed_bytes": 4096,
            "retained_ranges": [{"start": 0, "end": 4096}],
            "complete": True,
            "drain_confirmed": True,
        },
    }


def make_diagnostic_manifest() -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "producer": "monitor-1",
        "complete": True,
        "manifest_ref": "file:explicit:diagnostics",
        "stages": [
            {
                "stage_id": "pytest",
                "name": "pytest",
                "status": "failed",
                "exit_code": 1,
                "diagnostic_refs": ["file:explicit:pytest-log"],
                "counts": {"failures": 1},
            }
        ],
    }


def digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def make_prepare_request(**overrides: object) -> dict[str, Any]:
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "creator": {
            "project": "sase",
            "run_id": "run-1",
            "agent_name": "agent-1",
        },
        "context": {
            "run_id": "run-1",
            "agent_id": "agent-1",
            "turn_nonce": "nonce-1",
            "plan_digest": digest("plan"),
            "context_digest": digest("context"),
            "obligation_ids": ["repo-main"],
        },
        "success_message": "Required checks passed in {duration}.",
        "verification_command": ["just", "check-full"],
        "declaration": {
            "schema_version": 2,
            "context_digest": digest("context"),
            "plan_digest": digest("plan"),
            "payloads": [
                {
                    "instance_id": "commit",
                    "payload": {
                        "repositories": [
                            {
                                "repo_id": "repo-main",
                                "action": "commit",
                                "message": "fix: finish the change",
                            }
                        ],
                        "deferrals": [],
                    },
                }
            ],
        },
        "observations": [
            {
                "repo_id": "repo-main",
                "kind": "main",
                "name": "main",
                "head": digest("head"),
                "head_tree": digest("head-tree"),
                "index_tree": digest("index-tree"),
                "complete": True,
                "paths": [
                    {
                        "path": "src/app.py",
                        "xy": "M",
                        "content_hash": digest("app"),
                        "mode": "100644",
                        "kind": "file",
                        "protected": False,
                        "foreign": False,
                    }
                ],
            }
        ],
        "executors": [
            {
                "instance_id": "commit",
                "provider_ref": "builtin@commit",
                "headless": True,
                "durable_replay": True,
                "requires_model": False,
            }
        ],
    }
    request.update(overrides)
    return request


def make_bound_intent() -> dict[str, Any]:
    return bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": seal_conditional_completion(make_prepare_request()),
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )


def make_passed_stage(stage_id: str, name: str) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "name": name,
        "status": "passed",
        "exit_code": 0,
        "diagnostic_refs": [],
        "counts": {},
        "retained_ranges": [],
        "capture_errors": [],
    }
