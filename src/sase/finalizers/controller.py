"""Host-owned finalizer controller entry point and execution loop."""

from __future__ import annotations

from sase.finalizers.controller_context import FinalizerControllerError
from sase.finalizers.controller_cycle import MAX_CONTROLLER_CYCLES
from sase.finalizers.controller_run import run_finalizers

__all__ = [
    "FinalizerControllerError",
    "MAX_CONTROLLER_CYCLES",
    "run_finalizers",
]
