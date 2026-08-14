"""Compatibility aliases for :mod:`sase.sase_agent`.

Historical imports used the agent-lane vocabulary.  New code should import
:class:`~sase.sase_agent.SaseAgentRef` and the ``sase_agent_*`` helpers.
These names remain as a narrow compatibility surface for existing callers
and serialized ``lane_*`` field aliases.
"""

from __future__ import annotations

from sase.sase_agent import (
    AgentLaneRef,
    SaseAgentRef,
    lane_name,
    lane_page_path,
    lane_ref_for_agent,
    lane_ref_for_lane_name,
    sase_agent_name,
    sase_agent_page_path,
    sase_agent_ref_for_name,
    sase_agent_ref_for_shell,
)

__all__ = [
    "AgentLaneRef",  # legacy compatibility alias
    "SaseAgentRef",
    "lane_name",  # legacy compatibility alias
    "lane_page_path",  # legacy compatibility alias
    "lane_ref_for_agent",  # legacy compatibility alias
    "lane_ref_for_lane_name",  # legacy compatibility alias
    "sase_agent_name",
    "sase_agent_page_path",
    "sase_agent_ref_for_name",
    "sase_agent_ref_for_shell",
]
