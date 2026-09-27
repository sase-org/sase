"""Map update-lane procs to durable journal attempts.

``update_attempt_for`` is pure and safe on the UI thread. The settle helper
wraps the blocking journal write, so callers must run it off the UI thread
(in a session-worker body or a dedicated settle worker).
"""

from __future__ import annotations

from typing import Any

from sase.ace._update_attempts_model import UpdateAttempt, new_update_attempt
from sase.ace.update_attempts import (
    UpdateAttemptsView,
    settle_update_attempt,
)

from ._proc_observer_models import ObservedProc, is_update_row
from .actions._proc_action_types import TrackedProcResult


def update_attempt_for(proc_info: ObservedProc) -> UpdateAttempt | None:
    """Return a journal attempt for update-lane rows, else ``None``."""
    if not is_update_row(proc_info):
        return None
    return new_update_attempt(
        label=proc_info.label,
        proc_type=proc_info.proc_type,
        started_at=proc_info.started_at.timestamp(),
    )


def settle_update_attempt_for_result(
    attempt: UpdateAttempt,
    result: TrackedProcResult[Any],
    *,
    output: str | None,
) -> UpdateAttemptsView | None:
    """Settle *attempt* from a worker result; collisions never ran, so skip them."""
    if result.collision:
        return None
    return settle_update_attempt(
        attempt,
        success=result.success,
        error=result.error or result.message,
        output=output,
    )


__all__ = [
    "settle_update_attempt_for_result",
    "update_attempt_for",
]
