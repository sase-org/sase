"""Compatibility wrapper for legacy expander imports."""

from __future__ import annotations

import sase.agent.xprompt_swarm as _xprompt_swarm

expand_multi_agent_xprompts_with_metadata = (
    _xprompt_swarm.expand_xprompt_swarms_with_metadata
)
xprompt_has_segment_separators = _xprompt_swarm.xprompt_has_segment_separators

__all__ = [
    "expand_multi_agent_xprompts_with_metadata",
    "xprompt_has_segment_separators",
]
