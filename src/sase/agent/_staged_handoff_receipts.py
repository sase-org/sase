"""Adoption-receipt storage and authorization."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.gate_intent import atomic_write_json
from sase.agent._staged_handoff_store import (
    STAGED_HANDOFF_RECEIPT_FILENAME,
    StagedHandoffError,
    acquire_handoff_locks,
    artifacts_root,
    path_exists,
    read_json_object,
)
from sase.core.staged_handoff import (
    StagedHandoffContractError,
    receipt_authorizes as rust_receipt_authorizes,
    receipt_transition_allowed as rust_receipt_transition_allowed,
    validate_staged_handoff_receipt,
)


def read_adoption_receipt(
    artifacts_dir: str | None = None,
) -> dict[str, Any] | None:
    """Return the adoption receipt, or ``None`` when absent.

    Malformed existing state is a refusal, not absence.
    """
    root = artifacts_root(artifacts_dir)
    path = root / STAGED_HANDOFF_RECEIPT_FILENAME
    if not path_exists(path):
        return None
    payload = read_json_object(path, label="staged handoff receipt")
    try:
        return validate_staged_handoff_receipt(payload)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(
            f"malformed staged handoff receipt {path.name}: {exc}"
        ) from exc


def write_adoption_receipt(
    receipt: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
) -> Path:
    """Validate and persist an adoption receipt.

    Receipt monotonicity is enforced: a racing hold never overwrites a
    matching adopted receipt, and a mismatched staged ID is a refusal.
    """
    root = artifacts_root(artifacts_dir)
    try:
        normalized = validate_staged_handoff_receipt(dict(receipt))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
    staged_id = normalized.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        raise StagedHandoffError("adoption receipt has no staged_id")
    with acquire_handoff_locks(root):
        path = root / STAGED_HANDOFF_RECEIPT_FILENAME
        current: dict[str, Any] | None = None
        if path_exists(path):
            current = read_json_object(path, label="staged handoff receipt")
        try:
            allowed = rust_receipt_transition_allowed(current, normalized, staged_id)
        except StagedHandoffContractError as exc:
            raise StagedHandoffError(str(exc)) from exc
        except ValueError as exc:
            raise StagedHandoffError(str(exc)) from exc
        if not allowed:
            raise StagedHandoffError(
                "a successful adoption receipt already owns this stage"
            )
        atomic_write_json(path, normalized)
        return path


def receipt_authorizes(receipt: Mapping[str, Any], staged_id: str) -> bool:
    """Return whether *receipt* authorizes adoption of *staged_id*."""
    try:
        return rust_receipt_authorizes(dict(receipt), staged_id)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
