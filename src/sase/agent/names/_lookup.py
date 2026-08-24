"""Compatibility exports for agent-name lookup helpers.

The implementation is split by responsibility:

* :mod:`_lookup_named` finds exact and historical agent names.
* :mod:`_lookup_groups` aggregates agent families and clans.
* :mod:`_lookup_resolution` resolves resume and wait references.
* :mod:`_lookup_workflow` performs the targeted workflow completion scan.

Name lookup consumes the artifact snapshot produced by
:func:`sase.core.agent_scan_facade.scan_agent_artifacts`, while workflow
completion deliberately uses a targeted direct walk for this performance-
sensitive path. Both scan artifacts across all project lifecycle states.
"""

from sase.agent.names._lookup_groups import (
    AgentClan,
    AgentClanMember,
    AgentFamily,
    AgentFamilyMember,
    find_agent_clan,
    find_agent_family,
    is_agent_clan_complete,
    is_agent_family_complete,
    most_recent_completed_clan_member,
    most_recent_completed_family_member,
)
from sase.agent.names._lookup_named import (
    find_named_agent,
    get_most_recent_agent_name,
)
from sase.agent.names._lookup_resolution import (
    fork_parent_wait_is_unreachable,
    resolve_resume_agent_name,
    resolve_wait_dependency,
)
from sase.agent.names._lookup_workflow import is_workflow_complete

__all__ = [
    "AgentClan",
    "AgentClanMember",
    "AgentFamily",
    "AgentFamilyMember",
    "find_agent_clan",
    "find_agent_family",
    "find_named_agent",
    "fork_parent_wait_is_unreachable",
    "get_most_recent_agent_name",
    "is_agent_clan_complete",
    "is_agent_family_complete",
    "is_workflow_complete",
    "most_recent_completed_clan_member",
    "most_recent_completed_family_member",
    "resolve_resume_agent_name",
    "resolve_wait_dependency",
]
