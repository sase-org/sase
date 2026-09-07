"""Fleet-contract ``sase_core_rs`` tests: cursor, operations, connection, and time."""

from __future__ import annotations

import pytest

from tests._fleet_contract_sase_core_rs_helpers import (
    _binding,
    _exact_locator,
    _known_installation_id,
    _resource_revision,
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
