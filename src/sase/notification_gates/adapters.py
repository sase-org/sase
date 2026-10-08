"""Registered typed projections for notification gate kinds.

Facade preserving the original import path. The implementation now lives in
:mod:`sase.notification_gates.adapter` (the adapter type), :mod:`sase.notification_gates.adapter_plan`
(plan behavior), and :mod:`sase.notification_gates.adapter_registry` (the table).
"""

from sase.notification_gates.adapter import GateAdapter
from sase.notification_gates.adapter_registry import (
    PRIVILEGED_GATE_ACTIONS,
    adapter_for_action,
    adapter_for_kind,
    registered_gate_kinds,
)

__all__ = [
    "PRIVILEGED_GATE_ACTIONS",
    "GateAdapter",
    "adapter_for_action",
    "adapter_for_kind",
    "registered_gate_kinds",
]
