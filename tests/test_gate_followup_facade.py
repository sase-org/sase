from __future__ import annotations

from sase.core.gate_followup_facade import (
    GATE_FOLLOWUP_WIRE_SCHEMA_VERSION,
    decide_gate_followup,
    gate_followup_attempt_id,
    _gate_followup_wire_schema_version,
)


def test_binding_schema_version_matches_python_constant() -> None:
    assert _gate_followup_wire_schema_version() == GATE_FOLLOWUP_WIRE_SCHEMA_VERSION


def test_incident_legacy_gate_is_interrupted_and_resume_eligible() -> None:
    decision = decide_gate_followup(
        {
            "schema_version": GATE_FOLLOWUP_WIRE_SCHEMA_VERSION,
            "mode": "diagnose",
            "gate_id": "c117f874-83de-4840-8405-58a8dc1efd66",
            "gate_kind": "plan",
            "gate_state": "answered",
            "already_settled": True,
            "followup_requested": True,
        }
    )
    assert decision["disposition"] == "interrupted"
    assert decision["recovery"] == "resume"
    assert decision["needs_attention"] is True
    assert decision["launch_allowed"] is False
    assert decision["resume_eligible"] is True


def test_resume_mode_allows_launch_for_the_incident() -> None:
    decision = decide_gate_followup(
        {
            "schema_version": GATE_FOLLOWUP_WIRE_SCHEMA_VERSION,
            "mode": "resume",
            "gate_id": "c117f874-83de-4840-8405-58a8dc1efd66",
            "gate_kind": "plan",
            "gate_state": "answered",
            "already_settled": True,
            "followup_requested": True,
        }
    )
    assert decision["launch_allowed"] is True


def test_attempt_id_is_stable() -> None:
    first = gate_followup_attempt_id("gate-1", "fp")
    second = gate_followup_attempt_id("gate-1", "fp")
    assert first == second
    assert len(first) == 64
