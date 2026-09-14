"""Tests for continuation node, intent, monitor, and delivery validation."""

from __future__ import annotations

import pytest

from sase.core.continuation_facade import (
    new_continuation_delivery_record,
    transition_continuation_delivery,
    validate_continuation_delivery_record,
    validate_continuation_intent,
    validate_continuation_node,
    validate_diagnostic_manifest,
    validate_monitor_result,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.rust import require_rust_binding
from tests.core._continuation_facade_helpers import (
    call_continuation_binding,
    make_diagnostic_manifest,
    make_monitor_result,
    make_node,
)


def test_schema_version_matches_rust_binding() -> None:
    binding = require_rust_binding("continuation_wire_schema_version")
    assert int(binding()) == CONTINUATION_WIRE_SCHEMA_VERSION


def test_node_intent_monitor_manifest_and_delivery_validation_round_trip() -> None:
    assert validate_continuation_node(make_node("root"))["node_id"] == "root"

    intent = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "intent-1",
        "next_action": "Continue from the retained monitor result.",
        "route": {"inherit_model": True, "inherit_effort": True},
        "outcome_policy_ref": "file:explicit:policy",
        "conditional_completion_ref": "file:explicit:completion",
    }
    assert validate_continuation_intent(intent)["intent_id"] == "intent-1"

    result = make_monitor_result("completed", exit_code=0)
    assert validate_monitor_result(result)["outcome"] == "completed"

    manifest = make_diagnostic_manifest()
    assert validate_diagnostic_manifest(manifest)["stages"][0]["stage_id"] == "pytest"

    delivery = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "key": {
            "monitor_id": "monitor-1",
            "result_id": "result-1",
            "branch": "failed",
        },
        "selected_action": "continue",
        "reserved_identity": "agent-1",
        "attempt_history": [
            {
                "attempt_id": "attempt-1",
                "status": "acknowledged",
                "recorded_at": "2026-09-11T12:02:00Z",
                "detail": "queued successor",
            }
        ],
        "acknowledged_by": "agent-1",
        "disposition": "acknowledged",
        "disposition_reason": "successor launch acknowledged by host",
    }
    assert (
        validate_continuation_delivery_record(delivery)["disposition"] == "acknowledged"
    )

    pending = new_continuation_delivery_record(
        {
            "key": {
                "monitor_id": "monitor-1",
                "result_id": "result-1",
                "branch": "failed",
            },
            "selected_action": "continue",
            "recorded_at": "2026-09-12T00:00:00Z",
        }
    )
    reserved = transition_continuation_delivery(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "record": pending,
            "target": "reserved",
            "reserved_identity": "acme--1",
            "recorded_at": "2026-09-12T00:00:01Z",
        }
    )
    assert reserved["disposition"] == "reserved"
    assert reserved["reserved_identity"] == "acme--1"

    launch_continuation = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "mode": "resume_requester",
        "required": True,
        "checkpoint": "Continue the phase after helper approval.",
        "context": {
            "SASE_AGENT_NAME": "agent--0",
            "SASE_BEAD_ID": "sase-1.2",
        },
        "resume_branches": ["approve", "reject", "timeout", "failed"],
        "terminal_branches": ["stopped"],
    }
    assert (
        call_continuation_binding(
            "continuation_validate_launch_requester_continuation",
            launch_continuation,
        )["mode"]
        == "resume_requester"
    )


def test_unknown_node_kind_and_schema_version_raise_value_error() -> None:
    bad_kind = make_node("bad", kind="bogus")
    with pytest.raises(ValueError, match="unknown variant"):
        validate_continuation_node(bad_kind)

    bad_version = make_node("bad-version")
    bad_version["schema_version"] = 99
    with pytest.raises(ValueError, match="unsupported"):
        validate_continuation_node(bad_version)
