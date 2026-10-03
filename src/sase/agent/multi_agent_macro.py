"""Compatibility wrapper for legacy expander imports."""

from __future__ import annotations

import sase.agent.macro_swarm as _macro_swarm

expand_multi_agent_macros_with_metadata = _macro_swarm.expand_macro_swarms_with_metadata
macro_has_segment_separators = _macro_swarm.macro_has_segment_separators

__all__ = [
    "expand_multi_agent_macros_with_metadata",
    "macro_has_segment_separators",
]
