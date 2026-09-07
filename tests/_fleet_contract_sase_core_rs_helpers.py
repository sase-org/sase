"""Shared builders for fleet-contract ``sase_core_rs`` binding tests."""

from __future__ import annotations

import copy
import json
from typing import Any

from sase.core.rust import require_rust_binding


INSTALLATION_ID_PREFIX = "sase_inst_v1_"


def _binding(name: str) -> Any:
    return require_rust_binding(name)


def _known_installation_id(hex_char: str) -> str:
    return f"{INSTALLATION_ID_PREFIX}{hex_char * 64}"


def _origin(installation_id: str) -> dict[str, Any]:
    return {"schema_version": 1, "installation_id": installation_id}


def _logical_locator(
    installation_id: str,
    *,
    agent_id: str = "agent-1",
    family_id: str | None = "family-1",
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": _origin(installation_id),
            "project_id": "sase-main",
        },
        "agent_id": agent_id,
        "family_id": family_id,
    }


def _exact_locator(
    installation_id: str, *, agent_id: str = "agent-1", run_id: str = "run-1"
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logical": _logical_locator(installation_id, agent_id=agent_id),
        "shell_id": f"shell-{agent_id}",
        "run_id": run_id,
        "attempt_id": "attempt-1",
    }


def _resource_revision(logical: dict[str, Any], revision: int) -> dict[str, Any]:
    logical_key = _binding("fleet_logical_locator_key")(logical)
    return {
        "schema_version": 1,
        "logical_key": logical_key,
        "revision": revision,
    }


def _content_handle(revision: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": "transcript-1",
        "kind": "transcript",
        "revision": revision,
        "digest": "a" * 64,
        "byte_len": 1024,
        "supports_range": True,
        "supports_growth": True,
    }


def _running_record() -> dict[str, Any]:
    return {
        "project_name": "SASE",
        "project_dir": "/tmp/project",
        "project_file": "/tmp/project.sase",
        "workflow_dir_name": "ace-run",
        "artifact_dir": "/tmp/artifacts/20260906120000",
        "timestamp": "20260906120000",
        "agent_meta": {
            "name": "athena.agent-1",
            "model": "gpt-5",
            "llm_provider": "codex",
            "agent_family": "family-1",
        },
        "running": {
            "pid": 1234,
            "model": "gpt-5",
            "llm_provider": "codex",
            "workspace_dir": "/tmp/workspace",
        },
        "raw_prompt_snippet": "Implement the approved plan",
        "has_done_marker": False,
    }


def _projection_request(
    installation_id: str,
    *,
    agent_id: str = "agent-1",
    run_id: str = "run-1",
    revision: int = 7,
) -> dict[str, Any]:
    logical = _logical_locator(installation_id, agent_id=agent_id)
    exact = _exact_locator(installation_id, agent_id=agent_id, run_id=run_id)
    resource_revision = _resource_revision(logical, revision)
    return {
        "schema_version": 1,
        "record": _running_record(),
        "logical_locator": logical,
        "owner_facts": {
            "schema_version": 1,
            "exact_locator": exact,
            "row_revision": resource_revision,
            "liveness": "alive",
            "connection_health": "online",
            "freshness": "fresh",
            "observed_at_unix": 10.0,
            "row_kind": "agent_shell",
            "current_instance": True,
            "dismissable": False,
            "needs_attention": False,
            "occupied_runner_slot": True,
            "container_projected_concrete_agent": False,
            "capabilities": {
                "schema_version": 1,
                "resource": ["stop", "content.read", "stop"],
                "host": [],
                "protocol": [],
            },
            "content_handles": [_content_handle(resource_revision)],
        },
    }


def _summary_for_agent(
    installation_id: str, *, agent_id: str, run_id: str, revision: int
) -> dict[str, Any]:
    request = _projection_request(
        installation_id,
        agent_id=agent_id,
        run_id=run_id,
        revision=revision,
    )
    return _binding("fleet_project_resolved_agent_summary")(request)


def _operation_key(operation_id: str = "op-1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "controller_id": "controller-1",
        "operation_id": operation_id,
    }


def _follow_record(
    logical: dict[str, Any],
    *,
    created_by: str,
    state: str,
    timestamp: float,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logical_locator": copy.deepcopy(logical),
        "logical_key": _binding("fleet_logical_locator_key")(logical),
        "created_by": created_by,
        "state": state,
        "created_at_unix": timestamp,
        "updated_at_unix": timestamp,
        "activated_at_unix": timestamp if state == "active" else None,
        "operation_key": _operation_key() if created_by == "dispatch" else None,
    }


def _tombstone(logical: dict[str, Any], timestamp: float) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "logical_locator": copy.deepcopy(logical),
        "logical_key": _binding("fleet_logical_locator_key")(logical),
        "unfollowed_at_unix": timestamp,
    }


def _assert_no_local_or_auth_data(value: Any) -> None:
    forbidden_keys = {
        "artifact_dir",
        "auth_header",
        "bearer_token",
        "pgid",
        "pid",
        "project_dir",
        "project_file",
        "workspace_dir",
    }

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            assert not (set(node) & forbidden_keys)
            for item in node.values():
                walk(item)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value)
    assert "/tmp/" not in json.dumps(value, sort_keys=True)
