"""Gate shells: processless agent-session members that own pending gate decisions."""

from typing import Any

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

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "GATE_PENDING_MARKER": ("sase.gate_turn.agent_handoff", "GATE_PENDING_MARKER"),
    "GateTurnCreation": ("sase.gate_turn.transaction", "GateTurnCreation"),
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
    "maybe_handoff_gate_from_agent": (
        "sase.gate_turn.agent_handoff",
        "maybe_handoff_gate_from_agent",
    ),
    "read_gate_turn_marker": ("sase.gate_turn.store", "read_gate_turn_marker"),
    "resolve_gate_turn_ref": ("sase.gate_turn.store", "resolve_gate_turn_ref"),
    "settle_gate_turn": ("sase.gate_turn.settlement", "settle_gate_turn"),
    "will_handoff_gate_to_agent_runner": (
        "sase.gate_turn.agent_handoff",
        "will_handoff_gate_to_agent_runner",
    ),
}


def __getattr__(name: str) -> Any:
    """Lazily load lifecycle helpers that pull in runner dependencies."""
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute = target
    from importlib import import_module

    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)


__all__ = [
    "GATE_PENDING_MARKER",
    "MIN_GATE_TURN_REF_LENGTH",
    "SHORT_GATE_ID_LENGTH",
    "GateTurnCreation",
    "GateTurnError",
    "GateTurnLaneError",
    "GateTurnRecord",
    "GateTurnRefError",
    "GateTurnState",
    "allocate_gate_suffix",
    "cancel_gate_turn",
    "create_gate_turn",
    "find_gate_turn_by_gate_id",
    "find_gate_turn_by_gate_id",
    "has_any_gate_turn",
    "is_gate_turn_member_record",
    "list_gate_turns",
    "maybe_handoff_gate_from_agent",
    "new_gate_turn_id",
    "read_gate_turn_marker",
    "resolve_gate_turn_ref",
    "settle_gate_turn",
    "short_gate_turn_id",
    "will_handoff_gate_to_agent_runner",
]
