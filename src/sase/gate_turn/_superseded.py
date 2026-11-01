"""Settle the gate turn of a lost gate intent a later declaration superseded.

A lost gate intent normally fails the run. When the agent later submitted an
accepted final declaration, the host honors that declaration instead: the
intent is discarded, and the matching gate-turn member (if any) is settled
``lost`` and its published notification withdrawn, exactly as the reclaim
chop would have done for an abandoned gate.
"""

from __future__ import annotations

from sase.gate_turn._lost_withdraw import withdraw_lost_gate
from sase.gate_turn._reclaim_pending import settle_lost_unless_creating
from sase.gate_turn.store import find_gate_turn_by_gate_id

SUPERSEDED_REASON = "gate intent superseded by a later accepted final declaration"


def settle_superseded_gate_turn(request_id: str | None) -> bool:
    """Settle ``request_id``'s non-terminal gate-turn member ``lost``.

    Returns True when this call settled the member and withdrew its gate.
    Members that are missing, already terminal, still being created, or still
    reachable are left to the reclaim chop's normal classification.
    """
    if not request_id:
        return False
    record = find_gate_turn_by_gate_id(None, request_id)
    if record is None or record.is_terminal:
        return False
    if settle_lost_unless_creating(record, SUPERSEDED_REASON) != "settled":
        return False
    withdraw_lost_gate(record)
    return True


__all__ = ["SUPERSEDED_REASON", "settle_superseded_gate_turn"]
