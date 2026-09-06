from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from sase.core.rust import require_rust_binding


FLEET_BINDINGS = {
    "fleet_contract_schema_version",
    "fleet_installation_identity_load",
    "fleet_installation_identity_ensure",
    "fleet_installation_identity_rotate",
    "fleet_installation_identity_migrate",
    "fleet_logical_locator_key",
    "fleet_instance_locator_key",
    "fleet_associate_owner_display_name",
    "fleet_project_resolved_agent_summary",
    "fleet_project_resolved_agent_detail",
    "fleet_validate_resolved_agent_summary",
    "fleet_count_logical_agents",
    "fleet_classify_cursor_replay",
    "fleet_operation_payload_fingerprint",
    "fleet_decide_operation_replay",
    "fleet_validate_connection_plan",
    "fleet_classify_runtime_duration",
    "fleet_classify_cache_freshness",
}

INSTALLATION_ID_PREFIX = "sase_inst_v1_"


def _binding(name: str) -> Any:
    return require_rust_binding(name)


def _known_installation_id(hex_char: str) -> str:
    return f"{INSTALLATION_ID_PREFIX}{hex_char * 64}"


def _origin(installation_id: str) -> dict[str, Any]:
    return {"schema_version": 1, "installation_id": installation_id}


def _logical_locator(
    installation_id: str, *, agent_id: str = "agent-1"
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "project": {
            "schema_version": 1,
            "origin": _origin(installation_id),
            "project_id": "sase-main",
        },
        "agent_id": agent_id,
        "family_id": "family-1",
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


def test_fleet_contract_bindings_are_reachable_through_strict_loader() -> None:
    for name in sorted(FLEET_BINDINGS):
        assert callable(require_rust_binding(name))
    assert _binding("fleet_contract_schema_version")() == 1


def test_installation_identity_bindings_persist_and_fence_changes(
    tmp_path: Path,
) -> None:
    load = _binding("fleet_installation_identity_load")
    ensure = _binding("fleet_installation_identity_ensure")
    rotate = _binding("fleet_installation_identity_rotate")
    migrate = _binding("fleet_installation_identity_migrate")

    assert load(str(tmp_path))["record"] is None

    first = ensure(str(tmp_path))
    installation_id = first["record"]["installation_id"]
    assert first["created"] is True
    assert installation_id.startswith(INSTALLATION_ID_PREFIX)
    assert "athena" not in installation_id
    assert "codex" not in installation_id

    second = ensure(str(tmp_path))
    assert second["created"] is False
    assert second["record"]["installation_id"] == installation_id

    with pytest.raises(ValueError, match="expected_installation_id"):
        rotate(
            str(tmp_path),
            {
                "schema_version": 1,
                "expected_installation_id": _known_installation_id("b"),
                "reason": "wrong precondition",
                "rotated_at_unix": 20.0,
            },
        )

    rotated = rotate(
        str(tmp_path),
        {
            "schema_version": 1,
            "expected_installation_id": installation_id,
            "reason": "operator requested",
            "rotated_at_unix": 20.0,
        },
    )
    rotated_id = rotated["new_record"]["installation_id"]
    assert rotated["old_record"]["installation_id"] == installation_id
    assert rotated_id != installation_id
    assert rotated["new_record"]["prior_installation_id"] == installation_id

    adopted_id = _known_installation_id("c")
    migrated = migrate(
        str(tmp_path),
        {
            "schema_version": 1,
            "expected_current_installation_id": rotated_id,
            "adopted_installation_id": adopted_id,
            "reason": "clone recovery",
            "adopted_at_unix": 30.0,
        },
    )
    assert migrated["prior_record"]["installation_id"] == rotated_id
    assert migrated["new_record"]["installation_id"] == adopted_id
    assert load(str(tmp_path))["record"]["installation_id"] == adopted_id


def test_locator_projection_and_validation_round_trip_without_local_data() -> None:
    installation_id = _known_installation_id("a")
    logical = _logical_locator(installation_id)
    exact = _exact_locator(installation_id)

    logical_key = _binding("fleet_logical_locator_key")(logical)
    exact_key = _binding("fleet_instance_locator_key")(exact)
    assert exact_key.startswith(logical_key)

    owner = _binding("fleet_associate_owner_display_name")(
        {
            "schema_version": 1,
            "logical_locator": logical,
            "owner_username": "bryan",
            "owner_machine_name": "athena",
            "display_name": "athena.agent-1",
            "display_alias": "agent-1",
        }
    )
    assert owner["owner_label"] == "bryan.athena"
    assert owner["logical_key"] == logical_key

    request = _projection_request(installation_id)
    summary = _binding("fleet_project_resolved_agent_summary")(request)
    assert summary["logical_key"] == logical_key
    assert summary["exact_key"] == exact_key
    assert summary["lifecycle"] == "running"
    assert summary["liveness"] == "alive"
    assert summary["connection_health"] == "online"
    assert summary["freshness"] == "fresh"
    assert summary["capabilities"]["resource"] == ["content.read", "stop"]
    assert summary["content"]["handle_count"] == 1
    assert summary["content"]["kinds"] == ["transcript"]
    assert _binding("fleet_validate_resolved_agent_summary")(summary) == summary
    _assert_no_local_or_auth_data(summary)

    detail = _binding("fleet_project_resolved_agent_detail")(request)
    assert detail["summary"] == summary
    assert detail["content_handles"][0]["id"] == "transcript-1"
    _assert_no_local_or_auth_data(detail)

    stale_request = copy.deepcopy(request)
    stale_request["owner_facts"]["connection_health"] = "offline"
    stale_request["owner_facts"]["freshness"] = "stale"
    stale = _binding("fleet_project_resolved_agent_summary")(stale_request)
    assert stale["lifecycle"] == "running"
    assert stale["connection_health"] == "offline"
    assert stale["freshness"] == "stale"

    no_exact = copy.deepcopy(request)
    no_exact["owner_facts"]["exact_locator"] = None
    with pytest.raises(ValueError, match="exact instance locator"):
        _binding("fleet_project_resolved_agent_summary")(no_exact)

    path_handle = copy.deepcopy(request)
    path_handle["owner_facts"]["content_handles"][0]["id"] = "/tmp/transcript"
    with pytest.raises(ValueError, match="content handle id"):
        _binding("fleet_project_resolved_agent_detail")(path_handle)


def test_count_contract_deduplicates_current_instances_and_buckets() -> None:
    installation_id = _known_installation_id("a")
    running_old = _summary_for_agent(
        installation_id, agent_id="agent-run", run_id="run-1", revision=1
    )
    running_new = _summary_for_agent(
        installation_id, agent_id="agent-run", run_id="run-2", revision=2
    )
    waiting = _summary_for_agent(
        installation_id, agent_id="agent-wait", run_id="run-1", revision=3
    )
    waiting["lifecycle"] = "waiting"
    waiting["status_bucket"] = "waiting"
    waiting["occupied_runner_slot"] = False
    attention = _summary_for_agent(
        installation_id, agent_id="agent-attn", run_id="run-1", revision=4
    )
    attention["needs_attention"] = True
    monitor = _summary_for_agent(
        installation_id, agent_id="agent-monitor", run_id="run-1", revision=5
    )
    monitor["row_kind"] = "monitor"

    counts = _binding("fleet_count_logical_agents")(
        {
            "schema_version": 1,
            "summaries": [monitor, attention, waiting, running_old, running_new],
        }
    )
    assert counts["basis"]["input_rows"] == 5
    assert counts["basis"]["selected_rows"] == 3
    assert counts["logical_agent_total"] == 3
    assert counts["running"] == 2
    assert counts["waiting"] == 1
    assert counts["attention"] == 1
    assert counts["occupied_runner_slots"] == 2

    ambiguous = copy.deepcopy(running_new)
    ambiguous["exact_locator"]["run_id"] = "run-ambiguous"
    ambiguous["exact_key"] = _binding("fleet_instance_locator_key")(
        ambiguous["exact_locator"]
    )
    with pytest.raises(ValueError, match="ambiguous current instances"):
        _binding("fleet_count_logical_agents")(
            {
                "schema_version": 1,
                "summaries": [running_new, ambiguous],
            }
        )


def test_cursor_operation_connection_and_time_contracts() -> None:
    installation_id = _known_installation_id("a")
    exact = _exact_locator(installation_id)
    revision = _resource_revision(exact["logical"], 9)
    classify_cursor = _binding("fleet_classify_cursor_replay")

    current = classify_cursor(
        {
            "schema_version": 1,
            "cursor": {
                "schema_version": 1,
                "store_generation": "gen-1",
                "sequence": 5,
            },
            "current_generation": "gen-1",
            "newest_sequence": 5,
            "oldest_replayable_sequence": 3,
            "deletion_history_complete": True,
        }
    )
    assert current["classification"] == "current"

    replay = classify_cursor(
        {
            "schema_version": 1,
            "cursor": {
                "schema_version": 1,
                "store_generation": "gen-1",
                "sequence": 4,
            },
            "current_generation": "gen-1",
            "newest_sequence": 5,
            "oldest_replayable_sequence": 5,
            "deletion_history_complete": True,
        }
    )
    assert replay["classification"] == "replayable"
    assert replay["replay_from_sequence"] == 5

    gap = classify_cursor(
        {
            "schema_version": 1,
            "cursor": {
                "schema_version": 1,
                "store_generation": "gen-1",
                "sequence": 2,
            },
            "current_generation": "gen-1",
            "newest_sequence": 5,
            "oldest_replayable_sequence": 5,
            "deletion_history_complete": True,
        }
    )
    assert gap["classification"] == "resync_required"
    assert gap["reason"] == "replay_gap"

    fingerprint = _binding("fleet_operation_payload_fingerprint")
    first_fingerprint = fingerprint({"schema_version": 1, "payload": {"b": 2, "a": 1}})
    second_fingerprint = fingerprint({"schema_version": 1, "payload": {"a": 1, "b": 2}})
    assert first_fingerprint == second_fingerprint
    assert len(first_fingerprint["sha256"]) == 64

    operation_key = {
        "schema_version": 1,
        "controller_id": "controller-a",
        "operation_id": "op-1",
    }
    decision_request = {
        "schema_version": 1,
        "key": operation_key,
        "payload_fingerprint": first_fingerprint,
        "target": exact,
        "resource_revision": revision,
        "now_unix": 10.0,
        "acceptance_window_seconds": 5.0,
        "existing_record": None,
    }
    decide = _binding("fleet_decide_operation_replay")
    accepted = decide(decision_request)
    receipt = accepted["receipt"]
    assert accepted["decision"] == "accept_new"
    assert receipt["expires_at_unix_ms"] == 15000

    replayed = decide(
        {
            **decision_request,
            "existing_record": {
                "schema_version": 1,
                "receipt": receipt,
                "tombstoned_at_unix_ms": None,
            },
        }
    )
    assert replayed["decision"] == "return_original_receipt"
    assert replayed["receipt"] == receipt

    conflicting = decide(
        {
            **decision_request,
            "payload_fingerprint": fingerprint(
                {"schema_version": 1, "payload": {"a": 2}}
            ),
            "existing_record": {
                "schema_version": 1,
                "receipt": receipt,
                "tombstoned_at_unix_ms": None,
            },
        }
    )
    assert conflicting["decision"] == "conflict"

    expired = decide(
        {
            **decision_request,
            "now_unix": 16.0,
            "existing_record": {
                "schema_version": 1,
                "receipt": receipt,
                "tombstoned_at_unix_ms": None,
            },
        }
    )
    assert expired["decision"] == "expired"

    validate_connection = _binding("fleet_validate_connection_plan")
    valid_plan = {
        "schema_version": 1,
        "provider_ref": "provider-a",
        "endpoint": "https://fleet.example.test/api",
        "credential_ref": "credential-a",
        "pinned_installation_id": installation_id,
        "connection_kind": "gateway",
        "tls": {
            "schema_version": 1,
            "mode": "system_roots",
            "ca_ref": None,
            "server_name_ref": None,
        },
    }
    assert validate_connection(valid_plan) == valid_plan
    with pytest.raises(ValueError, match="absolute https:// URL"):
        validate_connection({**valid_plan, "endpoint": "http://example.test"})
    with pytest.raises(ValueError, match="userinfo"):
        validate_connection({**valid_plan, "endpoint": "https://user@example.test/api"})
    with pytest.raises(ValueError, match="system_roots"):
        validate_connection(
            {
                **valid_plan,
                "tls": {
                    "schema_version": 1,
                    "mode": "system_roots",
                    "ca_ref": "ca-a",
                    "server_name_ref": None,
                },
            }
        )

    runtime = _binding("fleet_classify_runtime_duration")(
        {
            "schema_version": 1,
            "owner_started_at_unix": 1.0,
            "owner_stopped_at_unix": None,
            "owner_observed_at_unix": 4.5,
            "max_clock_anomaly_seconds": 1.0,
        }
    )
    assert runtime["elapsed_seconds"] == 3.5
    assert runtime["state"] == "running"

    clamped = _binding("fleet_classify_runtime_duration")(
        {
            "schema_version": 1,
            "owner_started_at_unix": 5.0,
            "owner_stopped_at_unix": None,
            "owner_observed_at_unix": 4.5,
            "max_clock_anomaly_seconds": 1.0,
        }
    )
    assert clamped["elapsed_seconds"] == 0.0
    assert clamped["clamped"] is True

    with pytest.raises(ValueError, match="non-finite float"):
        _binding("fleet_classify_runtime_duration")(
            {
                "schema_version": 1,
                "owner_started_at_unix": float("nan"),
                "owner_stopped_at_unix": None,
                "owner_observed_at_unix": 4.5,
                "max_clock_anomaly_seconds": 1.0,
            }
        )

    assert (
        _binding("fleet_classify_cache_freshness")(
            {
                "schema_version": 1,
                "viewer_monotonic_elapsed_seconds": None,
                "fresh_threshold_seconds": 3.0,
                "stale_threshold_seconds": 10.0,
            }
        )["freshness"]
        == "unknown"
    )
    assert (
        _binding("fleet_classify_cache_freshness")(
            {
                "schema_version": 1,
                "viewer_monotonic_elapsed_seconds": 11.0,
                "fresh_threshold_seconds": 3.0,
                "stale_threshold_seconds": 10.0,
            }
        )["freshness"]
        == "stale"
    )


def test_importing_primary_package_has_no_network_provider_side_effects() -> None:
    script = """
import json
import sys

import sase

forbidden_prefixes = (
    "sase.llm_provider",
    "sase.integrations.mobile_agents",
    "sase.integrations.mobile_gateway",
)
forbidden = sorted(
    name
    for name in sys.modules
    if name.startswith(forbidden_prefixes)
)
print(json.dumps(forbidden))
raise SystemExit(1 if forbidden else 0)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
