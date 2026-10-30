"""Publish a staged gate from its persisted payload and creator identity."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from sase.core.staged_handoff import (
    StagedHandoffContractError,
    validate_gate_staged_payload,
)
from sase.gate_turn.models import GateTurnError, GateTurnRecord
from sase.gate_turn.staged_contract import (
    load_staged_gate_resource_bytes,
    rehydrate_staged_gate_spec,
)
from sase.gate_turn.transaction import (
    GateTurnCreation,
    creator_context_from_persisted,
    publish_gate_turn,
)
from sase.notification_gates.model_results import GateCreationResult


def publish_staged_gate(
    payload: Mapping[str, Any],
    *,
    staged_id: str,
    artifacts_dir: str,
    before_auto_settle: Callable[[GateTurnRecord, GateCreationResult], None]
    | None = None,
) -> GateTurnCreation:
    """Publish one staged gate from persisted identity and frozen policy.

    The original agent environment is not consulted. Snapshot bytes replace
    source-backed resources so publication does not reopen the CLI working
    directory. Frozen auto state is consumed as-is.
    """
    try:
        normalized = validate_gate_staged_payload(dict(payload))
    except StagedHandoffContractError as exc:
        raise GateTurnError(f"invalid staged gate payload: {exc}") from exc
    spec = rehydrate_staged_gate_spec(normalized)
    creator_payload = normalized.get("creator")
    if not isinstance(creator_payload, Mapping):
        raise GateTurnError("staged gate payload has no creator object")
    creator = creator_context_from_persisted(creator_payload)
    frozen_auto = normalized.get("auto")
    if not isinstance(frozen_auto, Mapping):
        raise GateTurnError("staged gate payload has no frozen auto snapshot")
    resource_bytes = load_staged_gate_resource_bytes(
        artifacts_dir, staged_id, normalized
    )
    return publish_gate_turn(
        spec,
        creator=creator,
        before_auto_settle=before_auto_settle,
        frozen_auto=frozen_auto,
        resource_bytes=resource_bytes,
    )


__all__ = ["publish_staged_gate"]
