"""Owner-side settlement hooks for hand-off ToolRuns.

Proc and monitor settlement run before the owner row is finished, so the row
still reads ``settling``. The hooks here reconcile a hand-off run with the
terminal owner fact the settlement already holds, and deliver the once-only
notification for proc-owned runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.tool_run import tool_run_show
from sase.tool.liveness import reconcile_handoff_run
from sase.tool.owner import owner_fact_from_settlement

_UNSETTLED_STATES = frozenset({"created", "running"})


def _run_is_settled(run_id: str) -> bool:
    run = tool_run_show(run_id).get("run")
    if not isinstance(run, dict):
        return False
    state = str(run.get("state") or "")
    return bool(state) and state not in _UNSETTLED_STATES


def settle_tool_run_followup(state: dict[str, Any]) -> None:
    """Settle the hand-off run named by a proc's ``tool-run`` follow-up policy.

    Sets ``followup_outcome`` to ``tool-run-settled``, ``tool-run-unsettled``,
    or ``tool-run-error`` (with ``followup_error``). Never raises, and stays
    idempotent under a resumed settlement checkpoint: reconcile skips a
    settled run and the notification id is deterministic.
    """

    try:
        policy = state.get("followup")
        run_id = str(policy.get("run_id") or "") if isinstance(policy, dict) else ""
        if not run_id:
            state["followup_outcome"] = "tool-run-unsettled"
            return
        fact = owner_fact_from_settlement(
            "proc", str(state.get("proc_id") or ""), state
        )
        reconcile_handoff_run(run_id, fact)
        if not _run_is_settled(run_id):
            state["followup_outcome"] = "tool-run-unsettled"
            return
        from sase.tool.notify import deliver_handoff_settlement

        if deliver_handoff_settlement(run_id) == "failed":
            state["followup_outcome"] = "tool-run-error"
            state["followup_error"] = "tool run settlement notification failed"
            return
        state["followup_outcome"] = "tool-run-settled"
    except Exception as exc:  # noqa: BLE001 - settlement must never wedge.
        state["followup_outcome"] = "tool-run-error"
        state["followup_error"] = str(exc) or type(exc).__name__


def settle_monitor_tool_run(
    run_id: str, monitor_id: str, state: Mapping[str, Any]
) -> None:
    """Reconcile a monitor-owned hand-off run; best effort, never notifies."""

    try:
        fact = owner_fact_from_settlement("monitor", monitor_id, state)
        reconcile_handoff_run(run_id, fact)
    except Exception:  # noqa: BLE001 - monitor settlement must never wedge.
        pass


__all__ = ["settle_monitor_tool_run", "settle_tool_run_followup"]
