"""Tests for the thin Rust-backed Agent Hijack wrappers and wire parsing."""

from __future__ import annotations

from typing import Any

import pytest

from sase.agent.hijack.core import (
    advance_agent_hijack_record,
    agent_hijack_eligibility,
    agent_hijack_status_for_done_marker,
    agent_hijack_wire_schema_version,
    hijack_recovery_preview,
    hijack_recovery_preview_wire_schema_version,
    hijack_recovery_reconcile,
    hijack_recovery_reconcile_wire_schema_version,
)
from sase.core.agent_auto_restart_wire import AgentRecoveryWire
from sase.core.agent_scan_wire_conversion import _done_marker_from_dict
from tests._rust_extension_module_helpers import install_fake_rust_extension


def test_hijack_wrappers_call_the_registered_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[object, ...]]] = []

    def version() -> int:
        calls.append(("version", ()))
        return 1

    def eligibility(facts: dict[str, Any]) -> dict[str, Any]:
        calls.append(("eligibility", (facts,)))
        return {"schema_version": 1, "eligible": True, "code": None, "message": None}

    def advance(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        calls.append(("advance", (record, event)))
        return {**record, "state": "stopping", "revision": 1}

    def status(outcome: str | None, recovery: dict[str, Any] | None) -> str | None:
        calls.append(("status", (outcome, recovery)))
        return "ESCALATED"

    install_fake_rust_extension(
        monkeypatch,
        agent_hijack_wire_schema_version=version,
        agent_hijack_eligibility=eligibility,
        advance_agent_hijack_record=advance,
        agent_hijack_status_for_done_marker=status,
    )

    assert agent_hijack_wire_schema_version() == 1
    facts = {"schema_version": 1, "status": "RUNNING"}
    assert agent_hijack_eligibility(facts)["eligible"] is True
    record = {"schema_version": 1, "state": "requested"}
    event = {"event": "begin_stop"}
    assert advance_agent_hijack_record(record, event)["state"] == "stopping"
    recovery = AgentRecoveryWire(state="resolved", kind="hijack", model_changed=True)
    assert agent_hijack_status_for_done_marker("hijacked", recovery) == "ESCALATED"
    assert calls[-1] == (
        "status",
        (
            "hijacked",
            {
                "state": "resolved",
                "reason": None,
                "reason_text": None,
                "requested_at": None,
                "updated_at": None,
                "episode_id": None,
                "ledger_key": None,
                "kind": "hijack",
                "hijack_id": None,
                "action": None,
                "successor": None,
                "model_changed": True,
            },
        ),
    )


def test_recovery_preview_and_reconcile_wrappers_call_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def preview_version() -> int:
        calls.append(("preview_version", ()))
        return 1

    def preview(request: dict[str, Any]) -> dict[str, Any]:
        calls.append(("preview", request))
        return {
            "schema_version": 1,
            "hijack_id": request["hijack_id"],
            "revision": 4,
            "default_action": "escalate",
            "actions": [],
        }

    def reconcile_version() -> int:
        calls.append(("reconcile_version", ()))
        return 1

    def reconcile(record: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
        calls.append(("reconcile", (record, facts)))
        return {
            "schema_version": 1,
            "outcome": "keep_resolving",
            "code": "live_resolver",
            "message": "live",
            "successor_name": "agent.2",
            "launch_identity": None,
        }

    install_fake_rust_extension(
        monkeypatch,
        hijack_recovery_preview_wire_schema_version=preview_version,
        hijack_recovery_preview=preview,
        hijack_recovery_reconcile_wire_schema_version=reconcile_version,
        hijack_recovery_reconcile=reconcile,
    )

    request = {"schema_version": 1, "hijack_id": "h-1", "state": "held"}
    facts = {"schema_version": 1, "successor": {"kind": "absent"}}
    record = {"schema_version": 1, "state": "resolving"}
    assert hijack_recovery_preview_wire_schema_version() == 1
    assert hijack_recovery_preview(request)["default_action"] == "escalate"
    assert hijack_recovery_reconcile_wire_schema_version() == 1
    assert hijack_recovery_reconcile(record, facts)["outcome"] == "keep_resolving"
    assert ("preview", request) in calls
    assert ("reconcile", (record, facts)) in calls


def test_scan_wire_preserves_hijack_recovery_fields() -> None:
    done = _done_marker_from_dict(
        {
            "outcome": "hijacked",
            "recovery": {
                "state": "resolved",
                "kind": "hijack",
                "hijack_id": "h-1",
                "action": "escalate",
                "successor": "agent.2",
                "model_changed": True,
            },
        }
    )
    assert done.recovery is not None
    assert done.recovery.kind == "hijack"
    assert done.recovery.hijack_id == "h-1"
    assert done.recovery.model_changed is True
