"""Reusable child-process supervision primitives.

Backoff/crash-loop bookkeeping, bounded output pumping, and SIGTERM->SIGKILL
termination, extracted from the AXE orchestrator so other supervisors (the
service host, in particular) can reuse the same proven mechanics instead of
duplicating them.
"""

from .logs import pump_output
from .restart import RestartPolicy, RestartState, record_started, schedule_restart
from .termination import send_sigterm, wait_with_escalation

__all__ = [
    "RestartPolicy",
    "RestartState",
    "pump_output",
    "record_started",
    "schedule_restart",
    "send_sigterm",
    "wait_with_escalation",
]
