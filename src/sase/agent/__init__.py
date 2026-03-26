"""Agent lifecycle subpackage.

Groups the agent-launching, naming, and multi-prompt orchestration modules.
"""

from sase.agent.launcher import (
    AgentLaunchResult,
    launch_agent_from_cwd,
    spawn_agent_subprocess,
)
from sase.agent.multi_prompt import (
    MultiPrompt,
    is_multi_prompt,
    parse_multi_prompt,
)
from sase.agent.multi_prompt_launcher import (
    deserialize_local_xprompts,
    launch_multi_prompt_agents,
)
from sase.agent.names import (
    claim_agent_name,
    find_named_agent,
    get_most_recent_agent_name,
    get_next_auto_name,
)
from sase.agent.running import (
    kill_named_agent,
    list_running_agents,
)

__all__ = [
    "AgentLaunchResult",
    "MultiPrompt",
    "claim_agent_name",
    "deserialize_local_xprompts",
    "find_named_agent",
    "get_most_recent_agent_name",
    "get_next_auto_name",
    "is_multi_prompt",
    "kill_named_agent",
    "launch_agent_from_cwd",
    "launch_multi_prompt_agents",
    "list_running_agents",
    "parse_multi_prompt",
    "spawn_agent_subprocess",
]
