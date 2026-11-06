"""Shared data and validation primitives for strict recovery successors."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Environment variable carrying the JSON-encoded recovery lineage. The
#: child boot persists it into ``agent_meta.json`` as ``recovery_lineage``.
#: ``hijack_lineage`` is the established canonical key the escalation walk
#: and recovery preview read; new boots write both keys with the same payload
#: while the mixed naming is audited out (see ``_apply_recovery_lineage``).
RECOVERY_LINEAGE_ENV = "SASE_HIJACK_RECOVERY_LINEAGE"

#: Canonical lineage key in ``agent_meta.json``. The escalation target walk
#: and recovery preview read this key; the child boot writes it alongside
#: the historical ``recovery_lineage`` alias so either reader observes the
#: same ``{hijack_id, from_rung, to_rung, predecessor}`` payload.
HIJACK_LINEAGE_META_KEY = "hijack_lineage"

#: Historical lineage key in ``agent_meta.json``. Kept as an alias of
#: :data:`HIJACK_LINEAGE_META_KEY` until every reader is audited.
RECOVERY_LINEAGE_META_KEY = "recovery_lineage"

#: Environment variable carrying the JSON-encoded reservation descriptor for
#: a strict recovery successor. The executor binds one validated descriptor
#: per CAS reservation; the child boot decodes it before provider execution
#: and fails closed when it is missing or malformed.
RECOVERY_DESCRIPTOR_ENV = "SASE_HIJACK_RECOVERY_DESCRIPTOR"

#: Wire schema version for the bootstrap ack and reservation descriptor.
#: Mirrors ``AGENT_HIJACK_EXECUTION_WIRE_SCHEMA_VERSION`` in
#: ``sase_core::agent_hijack::execution``; Python owns the file effects, the
#: core owns the confirmation/rollback decisions that consume these shapes.
BOOTSTRAP_ACK_SCHEMA_VERSION = 1

#: Environment marker requesting strict recovery boot semantics: the commit
#: finalizer baseline must be inherited (never freshly captured) and any
#: opened-repository inheritance diagnostic fails the boot.
RECOVERY_STRICT_ENV = "SASE_HIJACK_RECOVERY_STRICT"

#: Filename of the staged inheritance acknowledgement inside a successor's
#: artifacts directory. The CAS transaction observes it before confirming
#: the resolved recovery.
RECOVERY_ACK_FILENAME = "hijack_recovery_ack.json"

#: ``agent_meta.json`` keys that stay with their original turn. Verification
#: receipts and provider declarations are never copied to a successor: a
#: prepared child meta carrying a predecessor's values for these keys is a
#: preparation bug, not an inheritance.
NON_INHERITABLE_VERDICT_KEYS = (
    "outcome",
    "done",
    "receipts",
    "verdict_receipts",
    "declarations",
    "finalizer_declarations",
)


class RecoveryInheritanceError(RuntimeError):
    """A required recovery transfer failed validation before execution."""


class RecoveryBootstrapError(RecoveryInheritanceError):
    """A typed bootstrap stop before provider execution.

    The child boot raises this (instead of a bare
    :class:`RecoveryInheritanceError`) when the reservation descriptor or any
    required inheritance step fails, so the runner can record a
    machine-readable ``code`` alongside the message. ``code`` names the
    failed step (``missing_descriptor``, ``identity_mismatch``,
    ``goal_mismatch``, ``bead_mismatch``, ``scope_missing``,
    ``baseline_mismatch``, ``inventory_mismatch``, ``model_mismatch``); the
    provider is never invoked after this raises.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class RecoveryLineage:
    """Durable identity linking a recovery successor to its hijack."""

    hijack_id: str
    from_rung: str
    to_rung: str
    predecessor: str

    def as_dict(self) -> dict[str, str]:
        """Return the ``agent_meta.json`` payload for this lineage."""
        return {
            "hijack_id": self.hijack_id,
            "from_rung": self.from_rung,
            "to_rung": self.to_rung,
            "predecessor": self.predecessor,
        }


def normalize_recovery_lineage(
    lineage: RecoveryLineage | Mapping[str, Any],
) -> RecoveryLineage:
    """Validate *lineage* and return it as a :class:`RecoveryLineage`."""
    if isinstance(lineage, RecoveryLineage):
        payload = lineage.as_dict()
    elif isinstance(lineage, Mapping):
        payload = dict(lineage)
    else:
        raise RecoveryInheritanceError(
            f"recovery lineage must be a mapping, got {type(lineage).__name__}"
        )
    missing = [
        key
        for key in ("hijack_id", "from_rung", "to_rung", "predecessor")
        if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
    ]
    if missing:
        raise RecoveryInheritanceError(
            f"recovery lineage is missing required fields: {', '.join(missing)}"
        )
    return RecoveryLineage(
        hijack_id=str(payload["hijack_id"]).strip(),
        from_rung=str(payload["from_rung"]).strip(),
        to_rung=str(payload["to_rung"]).strip(),
        predecessor=str(payload["predecessor"]).strip(),
    )


def encode_recovery_lineage(lineage: RecoveryLineage | Mapping[str, Any]) -> str:
    """Encode *lineage* for transport in the successor environment."""
    return json.dumps(normalize_recovery_lineage(lineage).as_dict(), sort_keys=True)


def decode_recovery_lineage(raw: str | None) -> RecoveryLineage:
    """Decode a lineage payload, raising on missing or malformed input."""
    if not isinstance(raw, str) or not raw.strip():
        raise RecoveryInheritanceError(
            f"recovery requires a lineage payload ({RECOVERY_LINEAGE_ENV} is missing)"
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecoveryInheritanceError(
            f"recovery lineage payload is not valid JSON: {exc}"
        ) from exc
    return normalize_recovery_lineage(payload)


def ensure_no_verdict_carryover(
    *,
    parent_meta: Mapping[str, Any] | None,
    child_meta: Mapping[str, Any] | None,
) -> None:
    """Reject a successor meta that copied the predecessor's verdicts.

    Verification receipts and provider declarations stay with their original
    turn; the successor proves its own work from the inherited baseline.
    """
    if not isinstance(parent_meta, Mapping) or not isinstance(child_meta, Mapping):
        return
    carried = [
        key
        for key in NON_INHERITABLE_VERDICT_KEYS
        if key in child_meta
        and parent_meta.get(key) is not None
        and child_meta[key] == parent_meta[key]
    ]
    if carried:
        raise RecoveryInheritanceError(
            "recovery successor must not copy predecessor verdicts: "
            + ", ".join(sorted(carried))
        )


def require_narrowed_permission(
    *,
    predecessor_autonomy: Mapping[str, Any] | None,
    predecessor_name: str | None,
    explicit_autonomy_selection: str | None,
) -> dict[str, Any]:
    """Inherit the predecessor's permission scope without widening."""
    if not isinstance(predecessor_autonomy, Mapping) or not predecessor_autonomy:
        raise RecoveryInheritanceError(
            "recovery requires the predecessor's live permission record; "
            "an unreadable predecessor must not let the successor adopt a "
            "wider ambient policy"
        )
    from sase.autonomy.record import autonomy_inherit_record

    try:
        outcome = autonomy_inherit_record(
            dict(predecessor_autonomy),
            predecessor_name=str(predecessor_name or "unknown predecessor"),
            explicit_selection=explicit_autonomy_selection,
            actor_kind="host",
        )
    except Exception as exc:
        raise RecoveryInheritanceError(
            f"recovery permission inheritance failed: {exc}"
        ) from exc
    if not isinstance(outcome, dict) or not isinstance(outcome.get("record"), dict):
        raise RecoveryInheritanceError(
            "recovery permission inheritance produced no record"
        )
    if outcome.get("status") == "refused":
        raise RecoveryInheritanceError(
            "recovery permission inheritance refused widening: "
            f"{outcome.get('reason', 'unknown reason')}"
        )
    return dict(outcome["record"])
