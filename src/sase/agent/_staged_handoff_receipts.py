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
    """Validate and persist an adoption receipt."""
    root = artifacts_root(artifacts_dir)
    try:
        normalized = validate_staged_handoff_receipt(dict(receipt))
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
    with acquire_handoff_locks(root):
        path = root / STAGED_HANDOFF_RECEIPT_FILENAME
        atomic_write_json(path, normalized)
        return path


def receipt_authorizes(receipt: Mapping[str, Any], staged_id: str) -> bool:
    """Return whether *receipt* authorizes adoption of *staged_id*."""
    try:
        return rust_receipt_authorizes(dict(receipt), staged_id)
    except StagedHandoffContractError as exc:
        raise StagedHandoffError(str(exc)) from exc
