"""Launch planned chop proposals and record their results.

Split-implementation facade: the launch logic lives in the private
``_chop_proposal_launch_*`` modules. This module re-exports the public entry
point so the original import path keeps working.
"""

from __future__ import annotations

from ._chop_proposal_launch_runner import launch_chop_proposals

__all__ = ["launch_chop_proposals"]
