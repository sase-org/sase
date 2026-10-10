"""The update-skew healer: claim, verify, and relaunch once per lineage.

``sase agent auto-restart run`` executes these steps in order:

1. Claim the ledger, or exit if another claim is live.
2. Gather inputs and witnesses.
3. Classify.
4. Run the quiescence gate and the probe; on failure, mark ``deferred``.
5. Apply the skip rules.
6. Apply the storm breaker.
7. Write evidence.
8. Plan the restart.
9. Guard the wipe scope.
10. Execute.
11. Record the outcome.
12. Notify.

The claim is recorded before any mutation, and any uncertainty resolves to
"attempt spent, notify". A second pass never launches twice: a dead
``launching`` claim is adopted when the replacement exists, else settled
as failed and re-surfaced.

This module is a facade over the healer split: target resolution lives in
:mod:`sase.agent.auto_restart.healer_targets`, the ledger claim in
:mod:`sase.agent.auto_restart.healer_claim`, the claimed-pass orchestration
in :mod:`sase.agent.auto_restart.healer_flow`, the relaunch in
:mod:`sase.agent.auto_restart.healer_relaunch`, and shared plumbing in
:mod:`sase.agent.auto_restart._healer_common`.
"""

from __future__ import annotations

from sase.agent.auto_restart._healer_common import (
    HealerOutcome,
    HealerTarget,
    write_recovery,
)
from sase.agent.auto_restart.healer_claim import heal_one
from sase.agent.auto_restart.healer_targets import (
    resolve_pending_targets,
    resolve_targets,
)

__all__ = [
    "HealerOutcome",
    "HealerTarget",
    "heal_one",
    "resolve_pending_targets",
    "resolve_targets",
    "write_recovery",
]
