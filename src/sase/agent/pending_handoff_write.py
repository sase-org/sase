"""Admission guards for in-agent staged handoffs.

Historical pending markers remain readable in :mod:`sase.agent.pending_handoff`.
"""

from __future__ import annotations

import os
from pathlib import Path


class PendingHandoffError(RuntimeError):
    """Raised when a pending runner handoff cannot be started."""


def _refuse_finalizer_owned_handoff(command: str) -> None:
    """Raise when a finalizer-owned provider turn attempts a handoff."""
    from sase.finalizers.owned_turn import (
        finalizer_owned_turn_is_active,
        finalizer_owned_turn_refusal,
    )

    if finalizer_owned_turn_is_active():
        raise PendingHandoffError(finalizer_owned_turn_refusal(command))


def handoff_guard(*, command: str = "turn-ending handoffs") -> str:
    """Return the caller's artifacts dir, or raise if a handoff cannot start."""
    if not os.environ.get("SASE_AGENT"):
        raise PendingHandoffError("SASE_AGENT is unset")
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        raise PendingHandoffError("SASE_ARTIFACTS_DIR is unset")
    _refuse_finalizer_owned_handoff(command)
    from sase.agent.staged_handoff import (
        StagedHandoffError,
        acquire_handoff_locks,
        admit_stage,
    )

    try:
        with acquire_handoff_locks(Path(artifacts_dir)):
            admit_stage(command=command, artifacts_dir=artifacts_dir)
    except StagedHandoffError as exc:
        raise PendingHandoffError(str(exc)) from exc
    return artifacts_dir


__all__ = ["PendingHandoffError", "handoff_guard"]
