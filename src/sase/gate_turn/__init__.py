"""Gate turns: processless agent-session members that own pending gate decisions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "GATE_PENDING_MARKER": ("sase.gate_turn.agent_handoff", "GATE_PENDING_MARKER"),
    "GateTurnCreation": ("sase.gate_turn.transaction", "GateTurnCreation"),
    "STAGED_GATE_RESOURCES_DIRNAME": (
        "sase.gate_turn.staged_contract",
        "STAGED_GATE_RESOURCES_DIRNAME",
    ),
    "StagedGatePreparation": (
        "sase.gate_turn.staged_contract",
        "StagedGatePreparation",
    ),
    "collect_staged_gate_creator": (
        "sase.gate_turn.staged_contract",
        "collect_staged_gate_creator",
    ),
    "creator_context_from_persisted": (
        "sase.gate_turn.transaction",
        "creator_context_from_persisted",
    ),
    "discard_staged_gate_snapshot": (
        "sase.gate_turn.staged_contract",
        "discard_staged_gate_snapshot",
    ),
    "load_staged_gate_resource_bytes": (
        "sase.gate_turn.staged_contract",
        "load_staged_gate_resource_bytes",
    ),
    "prepare_staged_gate": (
        "sase.gate_turn.staged_contract",
        "prepare_staged_gate",
    ),
    "publish_gate_turn": (
        "sase.gate_turn.transaction",
        "publish_gate_turn",
    ),
    "publish_staged_gate": (
        "sase.gate_turn.publisher",
        "publish_staged_gate",
    ),
    "read_staged_gate_snapshot_bytes": (
        "sase.gate_turn.staged_contract",
        "read_staged_gate_snapshot_bytes",
    ),
    "rehydrate_staged_gate_spec": (
        "sase.gate_turn.staged_contract",
        "rehydrate_staged_gate_spec",
    ),
    "MIN_GATE_TURN_REF_LENGTH": (
        "sase.gate_turn.store",
        "MIN_GATE_TURN_REF_LENGTH",
    ),
    "cancel_gate_turn": ("sase.gate_turn.cancel", "cancel_gate_turn"),
    "create_gate_turn": ("sase.gate_turn.transaction", "create_gate_turn"),
    "find_gate_turn_by_gate_id": (
        "sase.gate_turn.store",
        "find_gate_turn_by_gate_id",
    ),
    "has_any_gate_turn": ("sase.gate_turn.store", "has_any_gate_turn"),
    "list_gate_turns": ("sase.gate_turn.store", "list_gate_turns"),
    "read_gate_turn_marker": ("sase.gate_turn.store", "read_gate_turn_marker"),
    "resolve_gate_turn_ref": ("sase.gate_turn.store", "resolve_gate_turn_ref"),
    "settle_gate_turn": ("sase.gate_turn.settlement", "settle_gate_turn"),
    "GateTurnError": ("sase.gate_turn.models", "GateTurnError"),
    "GateTurnLaneError": ("sase.gate_turn.models", "GateTurnLaneError"),
    "GateTurnRecord": ("sase.gate_turn.models", "GateTurnRecord"),
    "GateTurnRefError": ("sase.gate_turn.models", "GateTurnRefError"),
    "GateTurnState": ("sase.gate_turn.models", "GateTurnState"),
    "is_gate_turn_member_record": (
        "sase.gate_turn.models",
        "is_gate_turn_member_record",
    ),
    "SHORT_GATE_ID_LENGTH": ("sase.gate_turn.naming", "SHORT_GATE_ID_LENGTH"),
    "allocate_gate_suffix": ("sase.gate_turn.naming", "allocate_gate_suffix"),
    "new_gate_turn_id": ("sase.gate_turn.naming", "new_gate_turn_id"),
    "short_gate_turn_id": ("sase.gate_turn.naming", "short_gate_turn_id"),
}


def __getattr__(name: str) -> Any:
    """Resolve package re-exports without importing models or settlement."""
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__


__all__ = [
    "GATE_PENDING_MARKER",
    "MIN_GATE_TURN_REF_LENGTH",
    "SHORT_GATE_ID_LENGTH",
    "STAGED_GATE_RESOURCES_DIRNAME",
    "GateTurnCreation",
    "GateTurnError",
    "GateTurnLaneError",
    "GateTurnRecord",
    "GateTurnRefError",
    "GateTurnState",
    "StagedGatePreparation",
    "allocate_gate_suffix",
    "cancel_gate_turn",
    "collect_staged_gate_creator",
    "create_gate_turn",
    "creator_context_from_persisted",
    "discard_staged_gate_snapshot",
    "find_gate_turn_by_gate_id",
    "has_any_gate_turn",
    "is_gate_turn_member_record",
    "list_gate_turns",
    "load_staged_gate_resource_bytes",
    "new_gate_turn_id",
    "prepare_staged_gate",
    "publish_gate_turn",
    "publish_staged_gate",
    "read_gate_turn_marker",
    "read_staged_gate_snapshot_bytes",
    "rehydrate_staged_gate_spec",
    "resolve_gate_turn_ref",
    "settle_gate_turn",
    "short_gate_turn_id",
]

if TYPE_CHECKING:
    from sase.gate_turn.agent_handoff import GATE_PENDING_MARKER
    from sase.gate_turn.cancel import cancel_gate_turn
    from sase.gate_turn.models import (
        GateTurnError,
        GateTurnLaneError,
        GateTurnRecord,
        GateTurnRefError,
        GateTurnState,
        is_gate_turn_member_record,
    )
    from sase.gate_turn.naming import (
        SHORT_GATE_ID_LENGTH,
        allocate_gate_suffix,
        new_gate_turn_id,
        short_gate_turn_id,
    )
    from sase.gate_turn.publisher import publish_staged_gate
    from sase.gate_turn.settlement import settle_gate_turn
    from sase.gate_turn.staged_contract import (
        STAGED_GATE_RESOURCES_DIRNAME,
        StagedGatePreparation,
        collect_staged_gate_creator,
        discard_staged_gate_snapshot,
        load_staged_gate_resource_bytes,
        prepare_staged_gate,
        read_staged_gate_snapshot_bytes,
        rehydrate_staged_gate_spec,
    )
    from sase.gate_turn.store import (
        MIN_GATE_TURN_REF_LENGTH,
        find_gate_turn_by_gate_id,
        has_any_gate_turn,
        list_gate_turns,
        read_gate_turn_marker,
        resolve_gate_turn_ref,
    )
    from sase.gate_turn.transaction import (
        GateTurnCreation,
        create_gate_turn,
        creator_context_from_persisted,
        publish_gate_turn,
    )
