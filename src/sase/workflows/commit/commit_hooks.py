"""Backward-compatible imports for commit hook helpers.

New code should import from ``bead_hooks``, ``command_hooks``, or ``plan_hooks``
according to the responsibility it needs.
"""

from sase.workflows.commit.bead_hooks import (
    apply_bead_commit_tag,
    close_assigned_bead_after_commit,
    handle_beads,
)
from sase.workflows.commit.command_hooks import (
    run_after_commit_hook,
    run_before_commit_hook,
)
from sase.workflows.commit.plan_hooks import handle_sase_plan

__all__ = [
    "apply_bead_commit_tag",
    "close_assigned_bead_after_commit",
    "handle_beads",
    "handle_sase_plan",
    "run_after_commit_hook",
    "run_before_commit_hook",
]
