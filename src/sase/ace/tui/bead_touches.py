"""Loader for per-agent bead touches from the touch index.

The implementation is split by responsibility across focused private
modules; this facade preserves the established import surface for TUI
callers.
"""

from __future__ import annotations

from sase.ace.tui._bead_touches_loader import (
    MAX_KEPT_TOUCHES,
    load_bead_touches_for_agent_context,
)
from sase.ace.tui._bead_touches_merge import (
    BEAD_READ_REF_PREFIX,
    BeadTouchEntry,
    merge_bead_touch_entries,
    own_bead_ids_for_agent,
)

__all__: list[str] = [
    "BEAD_READ_REF_PREFIX",
    "MAX_KEPT_TOUCHES",
    "BeadTouchEntry",
    "load_bead_touches_for_agent_context",
    "merge_bead_touch_entries",
    "own_bead_ids_for_agent",
]
