"""Facade coverage for recovery activation and claim wires."""

from __future__ import annotations

from typing import Any

from sase.core import recovery_facade as facade


def test_missing_bindings_do_not_grant_recovery(monkeypatch: Any) -> None:
    monkeypatch.setattr(facade, "optional_rust_binding", lambda _name: None)

    inspect = facade.inspect_recovery_activation("/beads", "alpha")
    assert inspect.state == facade.RECOVERY_STATE_MALFORMED
    assert inspect.recovery_enabled is False
    assert inspect.diagnostic == facade.RECOVERY_UNKNOWN_UNSUPPORTED_CORE

    armed = facade.arm_recovery_activation("/beads", {"project_id": "alpha"})
    assert armed.created is False
    assert armed.recovery_enabled is False

    created = facade.create_recovery_claim(
        "/beads",
        {
            "project_id": "alpha",
            "epic_id": "demo-1",
            "close_token": "demo-1.1:evt",
            "owner_machine": "athena",
            "proc_id": "proc-a",
            "request_fingerprint": "fp-a",
        },
    )
    assert created.local_winner is False
    assert created.state == facade.RECOVERY_STATE_REFUSED


def test_facade_maps_activation_and_claim_wires(monkeypatch: Any) -> None:
    def binding(name: str) -> Any:
        if name == "bead_recovery_claim_key":
            return lambda project, epic, token: f"{project}:{epic}:{token}"
        if name == "bead_recovery_inspect_activation":

            def inspect(_beads_dir: str, project_id: str) -> dict[str, Any]:
                return {
                    "schema_version": 1,
                    "project_id": project_id,
                    "state": "armed",
                    "recovery_enabled": True,
                    "activation": {
                        "schema_version": 1,
                        "project_id": project_id,
                        "armed_at": "2026-11-28T00:00:00Z",
                        "generation": 1,
                    },
                }

            return inspect
        if name == "bead_recovery_create_claim":

            def create(_beads_dir: str, request: dict[str, Any]) -> dict[str, Any]:
                return {
                    "schema_version": 1,
                    "claim_key": "abc",
                    "state": "created",
                    "created": True,
                    "local_winner": True,
                    "claim": {
                        "schema_version": 1,
                        "project_id": request["project_id"],
                        "epic_id": request["epic_id"],
                        "close_token": request["close_token"],
                        "owner_machine": request["owner_machine"],
                        "proc_id": request["proc_id"],
                        "request_fingerprint": request["request_fingerprint"],
                        "activation_generation": 1,
                        "created_at": "2026-11-28T12:00:00Z",
                    },
                }

            return create
        return None

    monkeypatch.setattr(facade, "optional_rust_binding", binding)

    assert facade.recovery_claim_key("alpha", "demo-1", "tok") == "alpha:demo-1:tok"
    inspect = facade.inspect_recovery_activation("/beads", "alpha")
    assert inspect.recovery_enabled is True
    assert inspect.activation is not None
    assert inspect.activation.armed_at == "2026-11-28T00:00:00Z"

    created = facade.create_recovery_claim(
        "/beads",
        {
            "project_id": "alpha",
            "epic_id": "demo-1",
            "close_token": "tok",
            "owner_machine": "athena",
            "proc_id": "proc-a",
            "request_fingerprint": "fp-a",
        },
    )
    assert created.local_winner is True
    assert created.claim is not None
    assert created.claim.proc_id == "proc-a"
