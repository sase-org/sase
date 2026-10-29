"""Tests for the staged-handoff thin adapter."""

from __future__ import annotations

import pytest

from sase.core.rust import require_rust_binding
from sase.core.staged_handoff import (
    STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
    StagedHandoffContractError,
    evaluate_stage_admission,
    receipt_authorizes,
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
