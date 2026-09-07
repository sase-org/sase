"""Fleet-contract ``sase_core_rs`` tests: bindings, identity, and projection."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest

from sase.core.rust import require_rust_binding
from tests._fleet_contract_sase_core_rs_helpers import (
    INSTALLATION_ID_PREFIX,
    _assert_no_local_or_auth_data,
    _binding,
    _exact_locator,
    _known_installation_id,
    _logical_locator,
    _projection_request,
)


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
    "fleet_follow_record_key",
    "fleet_reconcile_follow_records",
    "fleet_count_focus_and_fleet",
    "fleet_classify_cursor_replay",
    "fleet_operation_payload_fingerprint",
    "fleet_decide_operation_replay",
    "fleet_mutation_payload_fingerprint",
    "fleet_validate_mutation_request",
    "fleet_evaluate_mutation_precondition",
    "fleet_partition_bulk_targets",
    "fleet_project_attention",
    "fleet_attention_payload_fingerprint",
    "fleet_validate_attention_request",
    "fleet_evaluate_attention_precondition",
    "fleet_decide_attention_notices",
    "fleet_validate_connection_plan",
    "fleet_classify_runtime_duration",
    "fleet_classify_cache_freshness",
}


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
