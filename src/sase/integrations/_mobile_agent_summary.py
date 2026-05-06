"""Mobile-shaped agent list and display projections."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    MobileAgentBridgeError,
    MobileAgentListRequest,
    _PROMPT_SNIPPET_LIMIT,
    directive_name,
    optional_str,
    optional_uint,
    option_id,
)
from ._mobile_agent_context import (
    persist_last_mobile_project_context,
    project_context_from_project_value,
)
from ._mobile_agent_deps import (
    RunningAgentInfo,
    list_all_agents,
    list_running_agents,
)
from ._mobile_agent_state import latest_mobile_launch_context


def list_mobile_agents(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return mobile-shaped agent summaries for running/recent agents."""
    parsed = parse_list_request(request or {})
    agents = list_all_agents() if parsed.include_recent else list_running_agents()
    agents = filter_agents(agents, parsed)
    total_count = len(agents)
    if parsed.limit is not None:
        agents = agents[: parsed.limit]
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agents": [agent_summary(agent) for agent in agents],
        "total_count": total_count,
    }


def mobile_agent_resume_options() -> dict[str, Any]:
    """Return copy/share/direct-launch resume and wait prompt options."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent in list_all_agents():
        if not agent.name or agent.name in seen:
            continue
        seen.add(agent.name)
        quoted_name = directive_name(agent.name)
        options.extend(
            [
                {
                    "id": f"{option_id(agent.name)}:resume",
                    "agent_name": agent.name,
                    "kind": "resume",
                    "label": f"Resume {agent.name}",
                    "prompt_text": f"#resume:{quoted_name}\n",
                    "direct_launch_supported": True,
                },
                {
                    "id": f"{option_id(agent.name)}:wait",
                    "agent_name": agent.name,
                    "kind": "wait",
                    "label": f"Wait for {agent.name}",
                    "prompt_text": f"%wait:{quoted_name}\n",
                    "direct_launch_supported": True,
                },
            ]
        )
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "options": options,
    }


def parse_list_request(payload: dict[str, Any]) -> MobileAgentListRequest:
    raw_limit = payload.get("limit")
    limit: int | None = None
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise MobileAgentBridgeError("limit must be an integer") from exc
        if limit < 0:
            raise MobileAgentBridgeError("limit must be non-negative")

    status = payload.get("status")
    if status is not None and not isinstance(status, str):
        raise MobileAgentBridgeError("status must be a string")
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        raise MobileAgentBridgeError("project must be a string")
    device_id = optional_str(payload.get("device_id"))

    project_context = project_context_from_project_value(
        project.strip() if isinstance(project, str) and project.strip() else None
    )
    if project_context is not None:
        persist_last_mobile_project_context(device_id, project_context)

    return MobileAgentListRequest(
        include_recent=bool(payload.get("include_recent", False)),
        status=status.strip().upper() if status and status.strip() else None,
        project=project_context.project
        if project_context is not None
        else project.strip()
        if project and project.strip()
        else None,
        device_id=device_id,
        limit=limit,
    )


def filter_agents(
    agents: list[RunningAgentInfo],
    request: MobileAgentListRequest,
) -> list[RunningAgentInfo]:
    filtered = agents
    if request.project:
        filtered = [agent for agent in filtered if agent.project == request.project]
    if request.status:
        filtered = [
            agent for agent in filtered if agent.status.upper() == request.status
        ]
    return filtered


def agent_summary(agent: RunningAgentInfo) -> dict[str, Any]:
    name = agent.name or "(unnamed)"
    has_name = bool(agent.name)
    has_artifact_dir = bool(agent.artifacts_dir and Path(agent.artifacts_dir).is_dir())
    context = latest_mobile_launch_context(name) if has_name else None
    lineage = retry_lineage(agent.artifacts_dir, context)
    prompt = prompt_snippet(agent.prompt)

    return {
        "name": name,
        "project": agent.project or None,
        "status": agent.status.lower(),
        "pid": optional_uint(agent.pid),
        "model": agent.model,
        "provider": agent.provider,
        "workspace_number": optional_uint(agent.workspace_num),
        "started_at": agent.started_at.isoformat() if agent.started_at else None,
        "duration_seconds": optional_uint(agent.duration_seconds),
        "prompt_snippet": prompt,
        "has_artifact_dir": has_artifact_dir,
        "retry_lineage": lineage,
        "actions": {
            "can_resume": has_name,
            "can_wait": has_name,
            "can_kill": has_name and agent.status.upper() == "RUNNING",
            "can_retry": has_name and (has_artifact_dir or context is not None),
        },
        "display": {
            "title": name,
            "subtitle": subtitle(agent),
            "status_label": agent.status.replace("_", " ").title(),
        },
    }


def retry_lineage(
    artifacts_dir: str | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    empty = {
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "retry_attempt": None,
        "parent_agent_name": optional_str(context.get("source_agent_name"))
        if context is not None
        else None,
    }
    if not artifacts_dir:
        return empty
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "retry_of_timestamp": optional_str(data.get("retry_of_timestamp")),
        "retried_as_timestamp": optional_str(data.get("retried_as_timestamp")),
        "retry_chain_root_timestamp": optional_str(
            data.get("retry_chain_root_timestamp")
        ),
        "retry_attempt": optional_uint(data.get("retry_attempt")),
        "parent_agent_name": optional_str(data.get("parent_agent_name")),
    }


def prompt_snippet(prompt: str | None) -> str | None:
    if prompt is None:
        return None
    prompt = prompt.replace("\n", " ").strip()
    if len(prompt) <= _PROMPT_SNIPPET_LIMIT:
        return prompt
    return prompt[:_PROMPT_SNIPPET_LIMIT]


def subtitle(agent: RunningAgentInfo) -> str | None:
    parts = [part for part in (agent.project, agent.provider, agent.model) if part]
    return " - ".join(parts) if parts else None


def find_mobile_agent_summary(name: str) -> RunningAgentInfo | None:
    for agent in list_all_agents():
        if agent.name == name:
            return agent
    return None
