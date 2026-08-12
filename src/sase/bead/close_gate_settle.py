"""Settle a closed task bead's pending gate the moment ``sase bead close`` closes it.

``cancel_gate`` writes into ``~/.sase/notifications``, which ACE already watches
via inotify — settling the gate here is the whole fix; no new event channel is
needed. Settlement is best-effort: the bead is already closed and committed by
the time this runs, so a failure here must never surface as a close failure.
The chop's next reconciliation tick remains the backstop.
"""

from __future__ import annotations

import logging
from collections.abc import Collection

from sase.bead.gate_lookup import find_pending_bead_gates
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND
from sase.bead.task_gate import TASK_TRIAGE_KIND
from sase.notification_gates.models import GateError

_logger = logging.getLogger(__name__)

CLOSE_SETTLE_REASON = "bead_closed"
_CLOSE_SETTLE_GATE_KINDS = (TASK_TRIAGE_KIND, BEAD_SNOOZE_KIND)


def settle_closed_task_bead_gates(
    project: str | None,
    bead_ids: Collection[str],
    *,
    source: str = "cli",
) -> None:
    """Cancel the pending TaskTriage or BeadSnooze gate for each closed bead.

    Scans the gate directories once no matter how many beads a bulk close
    touches. Callers must pre-filter *bead_ids* to task beads that were just
    closed; an empty *bead_ids* or unresolved *project* does no filesystem
    work at all.
    """
    if not bead_ids or project is None:
        return
    from sase.notification_gates.executor import cancel_gate
    from sase.notification_gates.paths import bundle_paths

    for gate in find_pending_bead_gates(_CLOSE_SETTLE_GATE_KINDS):
        if gate.project != project or gate.bead_id not in bead_ids:
            continue
        try:
            cancel_gate(
                bundle_paths(gate.kind, gate.request_id).root,
                reason=CLOSE_SETTLE_REASON,
                source=source,
            )
        except Exception as exc:
            if isinstance(exc, GateError) and exc.code == "already_answered":
                continue
            _logger.warning(
                "Failed to settle %s gate for %s after close",
                gate.kind,
                gate.bead_id,
                exc_info=True,
            )


__all__ = ["CLOSE_SETTLE_REASON", "settle_closed_task_bead_gates"]
