"""Public facade for AgentList list-building helpers.

Implementation lives in sibling ``_agent_list_build_*`` modules; this
file re-exports the names that callers and tests historically import
from ``_agent_list_build``.
"""

from __future__ import annotations

from ._agent_list_build_analysis import (
    compute_tier_styles,
    compute_visible_parents,
    resolve_row,
)
from ._agent_list_build_patching import patch_row, try_remove_rows
from ._agent_list_build_rebuild import build_list

__all__ = [
    "build_list",
    "compute_tier_styles",
    "compute_visible_parents",
    "patch_row",
    "resolve_row",
    "try_remove_rows",
]
