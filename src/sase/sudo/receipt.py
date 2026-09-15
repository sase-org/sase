"""Receipt and ledger validation for sudo approvals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateError
from sase.sudo.core import DEFAULT_SUDO_CORE, SudoCoreBinding
from sase.sudo.models import contains_credential_shape


def validate_sudo_receipt(
    receipt: object,
    *,
    manifest_sha256: str,
    selected_command_ids: Sequence[str],
    manifest: Mapping[str, Any] | None = None,
    core: SudoCoreBinding = DEFAULT_SUDO_CORE,
) -> dict[str, Any]:
    """Return a normalized runner receipt or raise."""
    if not isinstance(receipt, Mapping):
        raise GateError("invalid_sudo_receipt", "receipt", "receipt must be an object")
    data = dict(receipt)
    if contains_credential_shape(data):
        raise GateError(
            "credential_field_rejected",
            "receipt",
            "sudo runner receipt contains credential-shaped data",
        )
    normalized = core.validate_ledger(data, manifest)
    if normalized.get("manifest_sha256") != manifest_sha256:
        raise GateError(
            "receipt_hash_mismatch",
            "receipt.manifest_sha256",
            "sudo runner receipt does not match the reviewed manifest",
        )
    entries = normalized.get("entries")
    if not isinstance(entries, list):
        raise GateError(
            "invalid_sudo_receipt", "receipt.entries", "entries must be an array"
        )
    allowed = set(selected_command_ids)
    seen: set[str] = set()
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.entries[{index}]",
                "ledger entry must be an object",
            )
        command_id = item.get("id")
        if command_id not in allowed:
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.entries[{index}].id",
                "ledger command id is not in the reviewed manifest",
            )
        if command_id in seen:
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.entries[{index}].id",
                "ledger command id is repeated",
            )
        seen.add(str(command_id))
    missing = sorted(allowed - seen)
    if missing:
        raise GateError(
            "invalid_sudo_receipt",
            "receipt.entries",
            f"ledger is missing command id(s): {', '.join(missing)}",
        )
    return normalized


__all__ = ["validate_sudo_receipt"]
