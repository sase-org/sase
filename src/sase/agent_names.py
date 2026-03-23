"""Backward-compat shim — use ``sase.agent.names`` instead."""

from sase.agent.names import (  # noqa: F401
    claim_agent_name,
    find_named_agent,
    get_most_recent_agent_name,
    get_next_auto_name,
    kill_named_agent,
    list_running_agents,
)
