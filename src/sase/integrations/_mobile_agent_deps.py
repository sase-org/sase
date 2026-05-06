"""Patchable dependency wrappers for mobile agent internals."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TypeVar

from sase.agent.launcher import AgentLaunchResult
from sase.agent.launcher import launch_agents_from_cwd as _real_launch_agents_from_cwd
from sase.agent.names import allocate_retry_name as _real_allocate_retry_name
from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.agent.running import KillResult, RunningAgentInfo
from sase.agent.running import kill_named_agent as _real_kill_named_agent
from sase.agent.running import list_all_agents as _real_list_all_agents
from sase.agent.running import list_running_agents as _real_list_running_agents

T = TypeVar("T", bound=Callable[..., object])


def _facade_override(name: str, fallback: T) -> T:  # noqa: UP047
    module = sys.modules.get("sase.integrations.mobile_agents")
    if module is None:
        return fallback
    value = module.__dict__.get(name)
    if callable(value) and value is not globals().get(name):
        return value  # type: ignore[return-value]
    return fallback


def launch_agents_from_cwd(prompt: str) -> list[AgentLaunchResult]:
    return _facade_override("launch_agents_from_cwd", _real_launch_agents_from_cwd)(
        prompt
    )


def allocate_retry_name(name: str) -> str:
    return _facade_override("allocate_retry_name", _real_allocate_retry_name)(name)


def kill_named_agent(name: str, *, exact_name: bool) -> KillResult:
    return _facade_override("kill_named_agent", _real_kill_named_agent)(
        name,
        exact_name=exact_name,
    )


def list_all_agents() -> list[RunningAgentInfo]:
    return _facade_override("list_all_agents", _real_list_all_agents)()


def list_running_agents() -> list[RunningAgentInfo]:
    return _facade_override("list_running_agents", _real_list_running_agents)()
