"""Deferred, coalesced bead-confirmation warmup for the Agents tab.

Row rendering and header building must never touch bead storage, so they can
only show the bead glyph / ``Bead:`` field from the cached bead display state
(see :mod:`sase.ace.tui.models.agent_bead`). This mixin warms that cache off
the startup-critical loader path: after an Agents refresh has applied and the
list has painted, a coalesced background worker resolves the small set of
visible rows whose bead candidate has not been checked recently, runs the
bead-store lookups off the event loop, and patches the affected rows in place
by identity when the confirmed state changes.

First paint and j/k navigation are never gated on bead confirmation; the glyph
and field fill in shortly after the TUI is already interactive. Expired values
keep rendering while they revalidate, and missing candidates stay silent until
the cache TTL asks for another check.

This module is the public facade for :class:`AgentBeadWarmupMixin`; the
implementation is split into narrow private mixins so each file stays small.
"""

from __future__ import annotations

from ._loading_bead_warmup_apply import AgentBeadWarmupApplyMixin
from ._loading_bead_warmup_candidates import AgentBeadWarmupCandidatesMixin
from ._loading_bead_warmup_scan import AgentBeadWarmupScanMixin
from ._loading_bead_warmup_types import (
    AgentBeadWarmupCandidates,
    AgentBeadWarmupResults,
)

__all__ = [
    "AgentBeadWarmupApplyMixin",
    "AgentBeadWarmupCandidates",
    "AgentBeadWarmupCandidatesMixin",
    "AgentBeadWarmupMixin",
    "AgentBeadWarmupResults",
    "AgentBeadWarmupScanMixin",
]


class AgentBeadWarmupMixin(
    AgentBeadWarmupScanMixin,
    AgentBeadWarmupCandidatesMixin,
    AgentBeadWarmupApplyMixin,
):
    """Schedule and apply deferred bead-confirmation warmups off startup."""
