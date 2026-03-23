"""Backward-compat shim — use ``sase.agent.multi_prompt_launcher`` instead."""

from sase.agent.multi_prompt_launcher import (  # noqa: F401
    deserialize_local_xprompts,
    launch_multi_prompt_agents,
)
