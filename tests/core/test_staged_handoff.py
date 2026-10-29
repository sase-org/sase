"""Tests for the staged-handoff thin adapter."""

from __future__ import annotations

import pytest

from sase.core.rust import require_rust_binding
from sase.core.staged_handoff import (
    STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
    StagedHandoffContractError,
    build_gate_staged_payload,
    evaluate_stage_admission,
    gate_staged_payload_schema_version,
    receipt_authorizes,
    validate_gate_staged_payload,
    validate_staged_handoff,
    validate_staged_handoff_receipt,
    wire_schema_version,
)

STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _plan_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "staged_id": STAGED_ID,
        "kind": "plan",
        "created_at": "2026-10-28T12:00:00Z",
        "payload": {
            "plan_file": "/tmp/archive/plan.md",
            "original_file": "/tmp/scratch/plan.md",
        },
        "successor_workspace": "none",
        "carry_allowed": False,
        "dirty_obligations_at_stage": [],
    }


def test_schema_version_matches_binding() -> None:
    assert STAGED_HANDOFF_WIRE_SCHEMA_VERSION == 1
    assert wire_schema_version() == STAGED_HANDOFF_WIRE_SCHEMA_VERSION
    binding = require_rust_binding("staged_handoff_wire_schema_version")
    assert int(binding()) == STAGED_HANDOFF_WIRE_SCHEMA_VERSION


def test_plan_record_round_trips() -> None:
    record = _plan_record()
    assert validate_staged_handoff(dict(record)) == record


def test_invalid_plan_record_raises_contract_error() -> None:
    record = _plan_record()
    record["carry_allowed"] = True
    with pytest.raises(StagedHandoffContractError, match="carry_allowed"):
        validate_staged_handoff(record)


def test_receipt_authorizes_matching_adopted_id() -> None:
    receipt = {
        "staged_id": STAGED_ID,
        "adopted_at": "2026-10-28T12:01:00Z",
        "outcome": "adopted",
        "refs": {"gate_id": "g1"},
    }
    assert validate_staged_handoff_receipt(dict(receipt)) == receipt
    assert receipt_authorizes(receipt, STAGED_ID) is True
    assert receipt_authorizes(receipt, "bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee") is False


def test_admission_refuses_legacy_marker() -> None:
    with pytest.raises(StagedHandoffContractError, match=".sase_plan_pending"):
        evaluate_stage_admission(
            {
                "schema_version": 1,
                "command": "sase plan propose",
                "is_agent": True,
                "artifacts_dir_present": True,
                "is_finalizer_owned": False,
                "is_native_helper": False,
                "occupying": [".sase_plan_pending"],
                "has_accepted_current_submission": False,
            }
        )


def _gate_payload() -> dict[str, object]:
    return {
        "gate_schema_version": 1,
        "request_id": "custom-stage-1",
        "spec": {
            "request_id": "custom-stage-1",
            "resources": [
                {
                    "path": "notes.md",
                    "role": "editable",
                    "executable": False,
                    "source": "/tmp/work/notes.md",
                }
            ],
        },
        "auto": {
            "decision": {"profile": "manual"},
            "policy_block": {},
            "auto_execute": False,
        },
        "resources": [
            {
                "path": "notes.md",
                "role": "editable",
                "executable": False,
                "sha256": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
                "size_bytes": 3,
                "origin": "/tmp/work/notes.md",
                "staged_relpath": "snapshots/notes.md",
            }
        ],
        "creator": {
            "project": "sase",
            "project_file": "/tmp/sase.sase",
            "artifacts_dir": "/tmp/artifacts/20261029T000000Z",
            "timestamp": "20261029T000000Z",
            "agent": "agent-1",
            "meta": {},
        },
        "workspace_mode": "inherit",
    }


def test_gate_payload_schema_version_matches_binding() -> None:
    assert gate_staged_payload_schema_version() == 1
    binding = require_rust_binding("gate_staged_payload_schema_version")
    assert int(binding()) == 1


def test_gate_payload_round_trips_through_binding() -> None:
    payload = _gate_payload()
    assert validate_gate_staged_payload(dict(payload)) == payload


def test_gate_payload_build_defaults_schema_version() -> None:
    payload = _gate_payload()
    del payload["gate_schema_version"]
    built = build_gate_staged_payload(dict(payload))
    assert built["gate_schema_version"] == 1
    assert validate_gate_staged_payload(dict(built)) == built


def test_gate_payload_binding_rejects_mismatch() -> None:
    payload = _gate_payload()
    payload["request_id"] = "custom-other"
    with pytest.raises(StagedHandoffContractError, match="payload.spec.request_id"):
        build_gate_staged_payload(payload)


def test_gate_record_validates_disposition_through_binding() -> None:
    record = {
        "schema_version": 1,
        "staged_id": STAGED_ID,
        "kind": "gate",
        "created_at": "2026-10-28T12:00:00Z",
        "payload": _gate_payload(),
        "successor_workspace": "inherit",
        "carry_allowed": True,
        "dirty_obligations_at_stage": [],
    }
    assert validate_staged_handoff(dict(record)) == record

    mismatched = dict(record)
    mismatched["successor_workspace"] = "none"
    mismatched["carry_allowed"] = False
    with pytest.raises(StagedHandoffContractError, match="successor_workspace"):
        validate_staged_handoff(mismatched)
