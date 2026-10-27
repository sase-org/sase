"""Recover run-owned bead closes after terminal host-finalization failure.

A provider may close its beads during its turn. When host finalization then
fails terminally — a commit that never landed, or a declaration recovery that
never produced a submission — every still-current ``done`` close attributable
to that run is undone through the canonical Rust bead mutation engine, with
close history archived, closed ancestors reopened, and one ``STITCH FAILED:``
note appended per affected close episode.

The coordinator runs at the terminal controller failure boundary inside
:func:`sase.finalizers.controller.run_finalizers`, so both the provider-turn
path and the monitor/prepared-completion path funnel through it. It never
raises and never turns the failed finalizer into a success: on recovery
storage or publication failure it retains the original finalizer error plus
an actionable diagnostic in the run artifacts, and the controller still raises
the original failure.

Eligibility (all must hold before any mutation):

- a stable host-run identity is available (never guessed from assignees or
  timestamps; human closes stay unattributed and are never recovered);
- no authentic handoff is pending;
- the run has repository obligations (clean/no-code completion skips);
- at least one obligated repository has no landing proof: no commit marker
  that matches the repository path *and* this run *and* carries a commit SHA
  with push not refused, and no accepted typed deferral covering it.

Landing proofs come from the existing finalizer ledger
(``commit_results.json``) and reconciliation code: never exit codes, never a
clean tree alone, and never a marker from another repository or attempt.

This module remains the public facade. Assessment, note rendering, and the
machine-lane coordinator live in focused sibling modules.
"""

from __future__ import annotations

from sase.finalizers._failed_close_recovery_apply import (
    RECOVERY_OUTCOME_FILENAME,
    RECOVERY_REQUEST_FILENAME,
    coordinate_failed_close_recovery,
)
from sase.finalizers._failed_close_recovery_assess import (
    STITCH_FAILED_NOTE_PREFIX,
    source_identity_scope,
)

__all__ = [
    "RECOVERY_OUTCOME_FILENAME",
    "RECOVERY_REQUEST_FILENAME",
    "STITCH_FAILED_NOTE_PREFIX",
    "coordinate_failed_close_recovery",
    "source_identity_scope",
]
