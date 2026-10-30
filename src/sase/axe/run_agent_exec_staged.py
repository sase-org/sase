"""Adopt staged handoffs after the ordinary finalizer controller settles.

This module preserves the historical
``sase.axe.run_agent_exec_staged`` import surface while the
implementation lives in smaller focused modules.
"""

from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged_adopters import STAGED_HANDOFF_ADOPTERS
from sase.axe.run_agent_exec_staged_custody import CARRIED_CUSTODY_META_KEY
from sase.axe.run_agent_exec_staged_dispatch import dispatch_completed_staged_handoff

__all__ = [
    "CARRIED_CUSTODY_META_KEY",
    "STAGED_HANDOFF_ADOPTERS",
    "StagedInlineContinuation",
    "dispatch_completed_staged_handoff",
]
