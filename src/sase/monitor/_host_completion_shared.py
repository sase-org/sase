"""Shared public helpers for host completion.

This is an already-private (``_``-prefixed) module: new host-completion
modules import these public names instead of sharing ``_``-prefixed
helpers across files.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.monitor.no_new_receipt import NoNewEvidence, evidence_provenance
from sase.turns.followup import FollowupLaunchResult

DEFAULT_RECOVERY_ACTION = (
    "Diagnose failures or stale verification, then finish the requested change."
)
HOST_COMPLETION_IDENTITY = "host-completion"
HOST_COMPLETED_OUTCOME = "host-completed"
COMPLETED_BY_HOST_STATUS = "completed_by_host"
NEEDS_ATTENTION_STATUS = "needs_attention"


@dataclass(frozen=True, slots=True)
class HostCompletionSettlement:
    """Settlement produced by attempting no-model host completion."""

    error: str | None = None
    launch_result: FollowupLaunchResult | None = None


def verdict_receipt_record(evidence: NoNewEvidence | None) -> dict[str, Any]:
    """Render the verdict-receipt block for host completion receipts."""

    if evidence is None:
        return {}
    return {"verdict_receipt": evidence_provenance(evidence)}


__all__ = [
    "COMPLETED_BY_HOST_STATUS",
    "DEFAULT_RECOVERY_ACTION",
    "HOST_COMPLETED_OUTCOME",
    "HOST_COMPLETION_IDENTITY",
    "HostCompletionSettlement",
    "NEEDS_ATTENTION_STATUS",
    "verdict_receipt_record",
]
