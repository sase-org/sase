"""Mobile agent kill and retry lifecycle operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    MobileAgentBridgeError,
    MobileAgentNotFoundError,
    MobileAgentNotRunningError,
    MobileAgentPermissionDeniedError,
    optional_str,
    optional_uint,
    required_bridge_str,
)
from ._mobile_agent_context import (
    persist_last_mobile_project_context,
    project_context_from_agent,
)
from ._mobile_agent_deps import (
    KillResult,
    allocate_retry_name,
    kill_named_agent,
    rewrite_retry_prompt_name,
)
from ._mobile_agent_launch import launch_mobile_prompt
from ._mobile_agent_state import (
    context_from_agent,
    latest_mobile_launch_context,
    mobile_kill_context,
    persist_mobile_kill_context,
    project_context_from_kill_or_launch_context,
    read_prompt_file,
)
from ._mobile_agent_summary import find_mobile_agent_summary


def kill_mobile_agent(request: dict[str, Any]) -> dict[str, Any]:
    """Kill a named agent and persist retry context for mobile follow-up."""
    name = required_bridge_str(request.get("name"), "name")
    before = find_mobile_agent_summary(name)
    result = kill_named_agent(name, exact_name=True)
    if not result.success:
        raise_lifecycle_error(result)

    persist_mobile_kill_context(name, request, before, result)
    persist_last_mobile_project_context(
        optional_str(request.get("device_id")),
        project_context_from_agent(before) if before is not None else None,
    )
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "name": name,
        "status": result.status or "killed",
        "pid": optional_uint(result.pid),
        "changed": bool(result.changed),
        "message": result.message,
    }


def retry_mobile_agent(request: dict[str, Any]) -> dict[str, Any]:
    """Retry an agent from artifacts or durable mobile launch context."""
    source_name = required_bridge_str(request.get("name"), "name")
    context = resolve_mobile_retry_context(source_name)
    prompt = retry_prompt_from_context(context, request)

    if request.get("kill_source_first") is True:
        result = kill_named_agent(source_name, exact_name=True)
        if not result.success and result.reason == "permission_denied":
            raise_lifecycle_error(result)

    retry_name = allocate_retry_name(context["agent_name"])
    retry_prompt = rewrite_retry_prompt_name(prompt, retry_name)
    launch = launch_mobile_prompt(
        retry_prompt,
        {
            **request,
            "name": None,
        },
        launch_kind="retry",
        source_agent_name=context["agent_name"],
        retry_of_agent=context["agent_name"],
        project_context=project_context_from_kill_or_launch_context(context),
    )
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "source_agent": context["agent_name"],
        "launch": launch,
    }


def raise_lifecycle_error(result: KillResult) -> None:
    if result.reason == "not_found":
        raise MobileAgentNotFoundError(result.message)
    if result.reason in {"already_completed", "missing_pid"}:
        raise MobileAgentNotRunningError(result.message)
    if result.reason == "permission_denied":
        raise MobileAgentPermissionDeniedError(result.message)
    raise MobileAgentBridgeError(result.message)


def resolve_mobile_retry_context(name: str) -> dict[str, Any]:
    live_agent = find_mobile_agent_summary(name)
    if live_agent is not None:
        context = context_from_agent(live_agent)
        stored = latest_mobile_launch_context(name)
        if stored is not None:
            context = {**stored, **{k: v for k, v in context.items() if v is not None}}
        return context

    stored = latest_mobile_launch_context(name)
    if stored is not None:
        return stored

    killed = mobile_kill_context(name)
    if killed is not None:
        return killed

    raise MobileAgentNotFoundError(f"No retry context found for agent '{name}'")


def retry_prompt_from_context(context: dict[str, Any], request: dict[str, Any]) -> str:
    override = optional_str(request.get("prompt_override"))
    if override and override.strip():
        return override.strip()

    raw_prompt_path = optional_str(context.get("raw_prompt_path"))
    artifact_dir = optional_str(context.get("artifact_dir"))
    prompt = read_prompt_file(raw_prompt_path)
    if prompt is None and artifact_dir:
        prompt = read_prompt_file(str(Path(artifact_dir) / "raw_xprompt.md"))
    if prompt is None:
        prompt = optional_str(context.get("prompt_snapshot")) or optional_str(
            context.get("raw_prompt")
        )
    if prompt is None or not prompt.strip():
        raise MobileAgentNotFoundError(
            f"No prompt context found for agent '{context['agent_name']}'"
        )
    return prompt.strip()
