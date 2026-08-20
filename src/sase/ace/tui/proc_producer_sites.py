"""Catalog of ACE proc-producer sites and related infrastructure."""

from __future__ import annotations

from sase.ace.tui._proc_producer_site import CallKind, _ProcProducerSite
from sase.ace.tui._proc_producer_sites_actions import ACTION_PRODUCERS
from sase.ace.tui._proc_producer_sites_infrastructure import INFRASTRUCTURE
from sase.ace.tui._proc_producer_sites_updates import UPDATE_PRODUCERS
from sase.ace.tui._proc_producer_sites_workflows import WORKFLOW_PRODUCERS

PRODUCTION_PRODUCERS: tuple[_ProcProducerSite, ...] = (
    *ACTION_PRODUCERS,
    *UPDATE_PRODUCERS,
    *WORKFLOW_PRODUCERS,
)

__all__ = [
    "CallKind",
    "INFRASTRUCTURE",
    "PRODUCTION_PRODUCERS",
]
