"""Receipt and ledger validation for sudo approvals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateError
from sase.sudo.models import contains_credential_shape

_TERMINAL_LEDGER_STATUSES = frozenset(
    {"ran", "command_failed", "skipped", "authentication_failed", "cancelled"}
)


def validate_sudo_receipt(
    receipt: object,
    *,
    manifest_sha256: str,
    selected_command_ids: Sequence[str],
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
    if data.get("manifest_sha256") != manifest_sha256:
        raise GateError(
            "receipt_hash_mismatch",
            "receipt.manifest_sha256",
            "sudo runner receipt does not match the reviewed manifest",
        )
    ledger = data.get("ledger")
    if not isinstance(ledger, list):
        raise GateError(
            "invalid_sudo_receipt", "receipt.ledger", "ledger must be an array"
        )
    seen: set[str] = set()
    allowed = set(selected_command_ids)
    for index, item in enumerate(ledger):
        if not isinstance(item, Mapping):
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.ledger[{index}]",
                "ledger entry must be an object",
            )
        command_id = item.get("id")
        status = item.get("status")
        if command_id not in allowed:
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.ledger[{index}].id",
                "ledger command id is not in the reviewed manifest",
            )
        if command_id in seen:
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.ledger[{index}].id",
                "ledger command id is repeated",
            )
        if status not in _TERMINAL_LEDGER_STATUSES:
            raise GateError(
                "invalid_sudo_receipt",
                f"receipt.ledger[{index}].status",
                "ledger status is unsupported",
            )
        seen.add(str(command_id))
    missing = sorted(allowed - seen)
    if missing:
        raise GateError(
            "invalid_sudo_receipt",
            "receipt.ledger",
            f"ledger is missing command id(s): {', '.join(missing)}",
        )
    return data


__all__ = ["validate_sudo_receipt"]
