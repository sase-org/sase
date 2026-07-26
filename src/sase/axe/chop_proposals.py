"""Prepare, preview, plan, and launch proposals returned by chops.

This module is the stable import surface for chop proposal handling. The
implementation lives in focused proposal planning and launch modules.
"""

from __future__ import annotations

from .chop_proposal_launch import launch_chop_proposals
from .chop_proposal_planning import (
    plan_chop_proposals,
    prepare_chop_proposals,
    proposal_previews,
)

__all__ = [
    "launch_chop_proposals",
    "plan_chop_proposals",
    "prepare_chop_proposals",
    "proposal_previews",
]
