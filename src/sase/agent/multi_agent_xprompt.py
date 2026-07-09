"""Compatibility wrapper for legacy expander imports."""

from __future__ import annotations

import sase.agent.xprompt_swarm as _xprompt_swarm

_ExpandedMultiAgentXPromptSegment = _xprompt_swarm._ExpandedXpromptSwarmSegment
_extract_top_level_xprompt_reference = (
    _xprompt_swarm._extract_top_level_xprompt_reference
)
_MultiAgentXPromptDepthError = _xprompt_swarm._XpromptSwarmDepthError
_MultiAgentXPromptError = _xprompt_swarm._XpromptSwarmError
_MultiAgentXPromptUsageError = _xprompt_swarm._XpromptSwarmUsageError
expand_xprompt_swarms_with_metadata = _xprompt_swarm.expand_xprompt_swarms_with_metadata
expand_multi_agent_xprompts_with_metadata = expand_xprompt_swarms_with_metadata
xprompt_has_segment_separators = _xprompt_swarm.xprompt_has_segment_separators

__all__ = [
    "_ExpandedMultiAgentXPromptSegment",
    "_extract_top_level_xprompt_reference",
    "_MultiAgentXPromptDepthError",
    "_MultiAgentXPromptError",
    "_MultiAgentXPromptUsageError",
    "expand_multi_agent_xprompts_with_metadata",
    "xprompt_has_segment_separators",
]
