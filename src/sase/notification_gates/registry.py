"""Public registry API for notification gates."""

from sase.notification_gates.adapters import (
    PRIVILEGED_GATE_ACTIONS,
    GateAdapter,
    adapter_for_action,
    adapter_for_kind,
    registered_gate_kinds,
)
from sase.notification_gates.validation import validate_gate_spec

__all__ = [
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "adapter_for_action",
    "adapter_for_kind",
    "registered_gate_kinds",
    "validate_gate_spec",
]
