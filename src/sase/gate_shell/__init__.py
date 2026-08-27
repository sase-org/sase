"""Gate shells: processless family members that own pending gate decisions."""

from typing import Any

from sase.gate_shell.models import (
    GateShellError,
    GateShellLaneError,
    GateShellRecord,
    GateShellRefError,
    GateShellState,
    is_gate_shell_member_record,
)
from sase.gate_shell.naming import (
    SHORT_GATE_ID_LENGTH,
    allocate_gate_suffix,
    new_gate_shell_id,
    short_gate_shell_id,
)

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "GATE_PENDING_MARKER": ("sase.gate_shell.handoff", "GATE_PENDING_MARKER"),
    "GateShellCreation": ("sase.gate_shell.transaction", "GateShellCreation"),
    "MIN_GATE_SHELL_REF_LENGTH": (
        "sase.gate_shell.store",
        "MIN_GATE_SHELL_REF_LENGTH",
    ),
    "cancel_gate_shell": ("sase.gate_shell.cancel", "cancel_gate_shell"),
    "create_gate_shell": ("sase.gate_shell.transaction", "create_gate_shell"),
    "find_gate_shell_by_gate_id": (
        "sase.gate_shell.store",
        "find_gate_shell_by_gate_id",
    ),
    "has_any_gate_shell": ("sase.gate_shell.store", "has_any_gate_shell"),
    "list_gate_shells": ("sase.gate_shell.store", "list_gate_shells"),
    "maybe_handoff_gate_from_agent": (
        "sase.gate_shell.handoff",
        "maybe_handoff_gate_from_agent",
    ),
    "read_gate_shell_marker": ("sase.gate_shell.store", "read_gate_shell_marker"),
    "resolve_gate_shell_ref": ("sase.gate_shell.store", "resolve_gate_shell_ref"),
    "settle_gate_shell": ("sase.gate_shell.settlement", "settle_gate_shell"),
    "will_handoff_gate_to_agent_runner": (
        "sase.gate_shell.handoff",
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
    "MIN_GATE_SHELL_REF_LENGTH",
    "SHORT_GATE_ID_LENGTH",
    "GateShellCreation",
    "GateShellError",
    "GateShellLaneError",
    "GateShellRecord",
    "GateShellRefError",
    "GateShellState",
    "allocate_gate_suffix",
    "cancel_gate_shell",
    "create_gate_shell",
    "find_gate_shell_by_gate_id",
    "has_any_gate_shell",
    "is_gate_shell_member_record",
    "list_gate_shells",
    "maybe_handoff_gate_from_agent",
    "new_gate_shell_id",
    "read_gate_shell_marker",
    "resolve_gate_shell_ref",
    "settle_gate_shell",
    "short_gate_shell_id",
    "will_handoff_gate_to_agent_runner",
]
