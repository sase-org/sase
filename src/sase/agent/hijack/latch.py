"""Target-indexed durable Agent Hijack latch primitives.

Rust owns transition, observation, reconciliation, and force policy. This
module preserves the public import path and delegates implementation details to
private modules.
"""

from __future__ import annotations

from typing import Any

from sase.agent.hijack._stop_models import StopDeps
from sase.agent.hijack._latch_common import (
    current_time,
    owner_identity_for,
    same_owner_anchor,
)
from sase.agent.hijack._latch_actions import (
    cancel_latch,
    moot_latch,
    observe_hijack_latch,
)
from sase.agent.hijack._latch_apply import (
    apply_latch_at_boundary,
    apply_reconciled_latch,
    complete_latch_application,
)
from sase.agent.hijack._latch_request import request_latch


def force_hijack_latch(
    target_key: str,
    *,
    deps: StopDeps | None = None,
    hijack_id: str | None = None,
) -> dict[str, Any]:
    """Explicitly interrupt a live latch owner after Rust's 120-second bound."""
    from sase.agent.hijack._latch_force import force_hijack_latch as force

    return force(target_key, deps=deps, hijack_id=hijack_id)


__all__ = [
    "apply_reconciled_latch",
    "apply_latch_at_boundary",
    "cancel_latch",
    "complete_latch_application",
    "current_time",
    "force_hijack_latch",
    "moot_latch",
    "owner_identity_for",
    "observe_hijack_latch",
    "request_latch",
    "same_owner_anchor",
]
