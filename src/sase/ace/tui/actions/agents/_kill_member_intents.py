"""Durable member-stop intents for bulk agent cleanup transactions.

Active proc shells and pending gates cannot be killed or dismissed like
ordinary agents. The TUI removes their rows optimistically and the durable
persist-cleanup proc stops each proc shell through its canonical stop and
cancels each gate through its canonical cancel, in the same bulk transaction
as the surrounding kills and dismissals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

AgentIdentity = tuple["AgentType", str, str | None]

MEMBER_STOP_REQUESTED_BY = "agent-cleanup"
GATE_CANCEL_REASON = "cancelled via Agents-tab x"


class MemberStopError(RuntimeError):
    """One or more member stops/cancels did not settle.

    Carries the identities whose rows the TUI must resurface: the stop or
    cancel never happened, so the rows must come back instead of staying
    tombstoned.
    """

    def __init__(
        self,
        message: str,
        resurface_identities: set[AgentIdentity] | None = None,
    ) -> None:
        super().__init__(message)
        self.resurface_identities: set[AgentIdentity] = set(resurface_identities or ())


def execute_proc_stop_intents(proc_stops: list[Agent]) -> set[AgentIdentity]:
    """Stop every proc shell in *proc_stops* and record its dismissal.

    Returns the identities that failed to stop. A missing or already-terminal
    proc record is an idempotent success: the row is still gone, so its
    dismissal is recorded either way.
    """
    from sase.ace.dismissed_procs import record_dismissed_procs

    failed: set[AgentIdentity] = set()
    settled_proc_ids: list[str] = []
    for agent in proc_stops:
        proc_id = agent.proc_id
        if not proc_id:
            continue
        try:
            _stop_one_proc_shell(proc_id)
        except Exception:
            failed.add(agent.identity)
            continue
        settled_proc_ids.append(proc_id)
    # Only settled stops record a dismissal. A failed stop resurfaces its
    # row, so persisting its id here would hide it again on the next load.
    if settled_proc_ids:
        record_dismissed_procs(settled_proc_ids)
    return failed


def _stop_one_proc_shell(proc_id: str) -> None:
    """Stop one proc shell through its canonical stop path."""
    from sase.procs.models import TERMINAL_PROC_STATUSES
    from sase.procs.store import get_proc
    from sase.procs.submission import stop_named_proc

    proc = get_proc(proc_id)
    if proc is None or proc.status in TERMINAL_PROC_STATUSES:
        return
    stop_named_proc(proc, requested_by=MEMBER_STOP_REQUESTED_BY)


def execute_gate_cancel_intents(gate_cancels: list[Agent]) -> set[AgentIdentity]:
    """Cancel every pending gate in *gate_cancels*.

    Returns the identities whose cancel did not settle. A missing or
    already-terminal gate record is an idempotent success. A record the
    cancel returns unchanged (its decision started executing under the
    cancel) must resurface: the gate is still pending and its row must come
    back.
    """
    failed: set[AgentIdentity] = set()
    for agent in gate_cancels:
        try:
            if not _cancel_one_gate_shell(agent):
                failed.add(agent.identity)
        except Exception:
            failed.add(agent.identity)
    return failed


def _cancel_one_gate_shell(agent: Agent) -> bool:
    """Cancel one pending gate shell; True when the cancel settled."""
    from sase.gate_turn.cancel import cancel_gate_turn
    from sase.gate_turn.store import list_gate_turns

    gate_id = agent.gate_id
    if not gate_id:
        return True
    record = next(
        (candidate for candidate in list_gate_turns() if candidate.gate_id == gate_id),
        None,
    )
    if record is None or record.is_terminal:
        return True
    result = cancel_gate_turn(record, reason=GATE_CANCEL_REASON)
    return bool(result.is_terminal and result.gate_state != record.gate_state)


__all__ = [
    "GATE_CANCEL_REASON",
    "MEMBER_STOP_REQUESTED_BY",
    "MemberStopError",
    "execute_gate_cancel_intents",
    "execute_proc_stop_intents",
]
