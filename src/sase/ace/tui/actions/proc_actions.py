"""Public façade for durable proc submission and observation actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._proc_action_completion import ProcCompletionActionsMixin
from ._proc_action_observer import (
    PROC_RECONCILE_INTERVAL_SECONDS,
    PROC_RECONCILE_STARTUP_DELAY_SECONDS,
)
from ._proc_action_types import (
    DurableSubmitWorkerResult as _DurableSubmitWorkerResult,
    ProcCallbackConfig as _ProcCallbackConfig,
    SessionWorkerResult as _SessionWorkerResult,
    TrackedProcCompletion,
    TrackedProcResult,
)

if TYPE_CHECKING:
    from ...patch import Patch


class ProcActionsMixin(ProcCompletionActionsMixin):
    """Mixin providing durable proc submission and read-only observation."""

    patches: list[Patch]
    current_idx: int


__all__ = [
    "PROC_RECONCILE_INTERVAL_SECONDS",
    "PROC_RECONCILE_STARTUP_DELAY_SECONDS",
    "ProcActionsMixin",
    "TrackedProcCompletion",
    "TrackedProcResult",
]

# Keep private module attributes available to existing test and integration code while
# the public import surface continues to live in this façade.
_COMPATIBILITY_EXPORTS = (
    _DurableSubmitWorkerResult,
    _ProcCallbackConfig,
    _SessionWorkerResult,
)
