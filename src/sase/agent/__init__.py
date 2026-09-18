"""Agent lifecycle subpackage.

Groups the agent-launching, naming, and multi-prompt orchestration modules.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "ArtifactFileCache": (".artifact_files_cache", "ArtifactFileCache"),
    "AgentLaunchResult": (".launcher", "AgentLaunchResult"),
    "MultiPrompt": (".multi_prompt", "MultiPrompt"),
    "TailCache": (".artifact_files_cache", "TailCache"),
    "claim_agent_name": (".names", "claim_agent_name"),
    "deserialize_local_xprompts": (
        ".multi_prompt_launcher",
        "deserialize_local_xprompts",
    ),
    "find_named_agent": (".names", "find_named_agent"),
    "get_global_cache": (".artifact_files_cache", "get_global_cache"),
    "get_most_recent_agent_name": (".names", "get_most_recent_agent_name"),
    "get_next_auto_name": (".names", "get_next_auto_name"),
    "is_multi_prompt": (".multi_prompt", "is_multi_prompt"),
    "kill_named_agent": (".running", "kill_named_agent"),
    "launch_agent_from_cwd": (".launcher", "launch_agent_from_cwd"),
    "launch_agents_from_cwd": (".launcher", "launch_agents_from_cwd"),
    "launch_multi_prompt_agents": (
        ".multi_prompt_launcher",
        "launch_multi_prompt_agents",
    ),
    "list_all_agents": (".running", "list_all_agents"),
    "list_running_agents": (".running", "list_running_agents"),
    "parse_multi_prompt": (".multi_prompt", "parse_multi_prompt"),
    "spawn_agent_subprocess": (".launcher", "spawn_agent_subprocess"),
}

__all__ = [
    "ArtifactFileCache",
    "AgentLaunchResult",
    "MultiPrompt",
    "TailCache",
    "claim_agent_name",
    "deserialize_local_xprompts",
    "find_named_agent",
    "get_global_cache",
    "get_most_recent_agent_name",
    "get_next_auto_name",
    "is_multi_prompt",
    "kill_named_agent",
    "launch_agent_from_cwd",
    "launch_agents_from_cwd",
    "launch_multi_prompt_agents",
    "list_all_agents",
    "list_running_agents",
    "parse_multi_prompt",
    "spawn_agent_subprocess",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


_PEP562_HOOKS = (__getattr__, __dir__)
