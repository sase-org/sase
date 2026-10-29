"""Thin adapter over the Rust staged-handoff wire contract.

The Rust core owns schema validation, kind invariants, receipt identity,
and staging-admission policy. This module mirrors the schema version and
routes every decision through ``sase_core_rs`` without a Python fallback.
"""

from __future__ import annotations

from typing import Any

from sase.core.rust import require_rust_binding

#: Mirrors Rust ``STAGED_HANDOFF_WIRE_SCHEMA_VERSION``.
STAGED_HANDOFF_WIRE_SCHEMA_VERSION = 1


class StagedHandoffContractError(ValueError):
    """Raised when a staged-handoff record, receipt, or admission fails."""


def wire_schema_version() -> int:
    """Return the Rust staged-handoff wire schema version."""
    binding = require_rust_binding("staged_handoff_wire_schema_version")
    return int(binding())


def validate_staged_handoff(record: dict[str, Any]) -> dict[str, Any]:
    """Validate a staged-handoff record dict via Rust."""
    binding = require_rust_binding("validate_staged_handoff")
    try:
        return dict(binding(record))
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc


def validate_staged_handoff_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Validate a staged-handoff adoption receipt dict via Rust."""
    binding = require_rust_binding("validate_staged_handoff_receipt")
    try:
        return dict(binding(receipt))
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc


def evaluate_stage_admission(request: dict[str, Any]) -> None:
    """Refuse staging when host observations violate the admission policy."""
    binding = require_rust_binding("evaluate_stage_admission")
    try:
        binding(request)
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc


def receipt_authorizes(receipt: dict[str, Any], staged_id: str) -> bool:
    """Return whether *receipt* authorizes adoption of *staged_id*."""
    binding = require_rust_binding("staged_handoff_receipt_authorizes")
    try:
        return bool(binding(receipt, staged_id))
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc


def gate_staged_payload_schema_version() -> int:
    """Return the Rust staged gate payload schema version."""
    binding = require_rust_binding("gate_staged_payload_schema_version")
    return int(binding())


def validate_gate_staged_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a staged gate payload dict via Rust."""
    binding = require_rust_binding("validate_gate_staged_payload")
    try:
        return dict(binding(payload))
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc


def build_gate_staged_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Assemble a staged gate payload from parts, defaulting then validating."""
    binding = require_rust_binding("build_gate_staged_payload")
    try:
        return dict(binding(payload))
    except StagedHandoffContractError:
        raise
    except ValueError as exc:
        raise StagedHandoffContractError(str(exc)) from exc
