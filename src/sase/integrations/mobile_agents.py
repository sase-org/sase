"""Read-only mobile agent bridge projections."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from sase.agent.running import (
    RunningAgentInfo,
    list_all_agents,
    list_running_agents,
)

MOBILE_AGENT_SCHEMA_VERSION = 1

_PROMPT_SNIPPET_LIMIT = 200
_SAFE_DIRECTIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class _MobileAgentBridgeError(RuntimeError):
    """Deterministic bridge error for JSON command failures."""


@dataclass(frozen=True)
class _MobileAgentListRequest:
    include_recent: bool = False
    status: str | None = None
    project: str | None = None
    limit: int | None = None


def _list_mobile_agents(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return mobile-shaped agent summaries for running/recent agents."""
    parsed = _parse_list_request(request or {})
    agents = list_all_agents() if parsed.include_recent else list_running_agents()
    agents = _filter_agents(agents, parsed)
    total_count = len(agents)
    if parsed.limit is not None:
        agents = agents[: parsed.limit]
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agents": [_agent_summary(agent) for agent in agents],
        "total_count": total_count,
    }


def _mobile_agent_resume_options() -> dict[str, Any]:
    """Return copy/share/direct-launch resume and wait prompt options."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent in list_all_agents():
        if not agent.name or agent.name in seen:
            continue
        seen.add(agent.name)
        quoted_name = _directive_name(agent.name)
        options.extend(
            [
                {
                    "id": f"{_option_id(agent.name)}:resume",
                    "agent_name": agent.name,
                    "kind": "resume",
                    "label": f"Resume {agent.name}",
                    "prompt_text": f"#resume:{quoted_name}\n",
                    "direct_launch_supported": True,
                },
                {
                    "id": f"{_option_id(agent.name)}:wait",
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


def handle_mobile_agent_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed mobile agent bridge operation over JSON stdin/stdout."""
    try:
        request = _read_request(stdin)
        operation = getattr(args, "mobile_agent_bridge_subcommand", None)
        if operation == "list-agents":
            response = _list_mobile_agents(request)
        elif operation == "resume-options":
            response = _mobile_agent_resume_options()
        else:
            raise _MobileAgentBridgeError("unknown mobile agent bridge operation")
    except (_MobileAgentBridgeError, ValueError, TypeError) as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def _read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _MobileAgentBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise _MobileAgentBridgeError("request JSON must be an object")
    return payload


def _parse_list_request(payload: dict[str, Any]) -> _MobileAgentListRequest:
    raw_limit = payload.get("limit")
    limit: int | None = None
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise _MobileAgentBridgeError("limit must be an integer") from exc
        if limit < 0:
            raise _MobileAgentBridgeError("limit must be non-negative")

    status = payload.get("status")
    if status is not None and not isinstance(status, str):
        raise _MobileAgentBridgeError("status must be a string")
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        raise _MobileAgentBridgeError("project must be a string")

    return _MobileAgentListRequest(
        include_recent=bool(payload.get("include_recent", False)),
        status=status.strip().upper() if status and status.strip() else None,
        project=project.strip() if project and project.strip() else None,
        limit=limit,
    )


def _filter_agents(
    agents: list[RunningAgentInfo],
    request: _MobileAgentListRequest,
) -> list[RunningAgentInfo]:
    filtered = agents
    if request.project:
        filtered = [agent for agent in filtered if agent.project == request.project]
    if request.status:
        filtered = [
            agent for agent in filtered if agent.status.upper() == request.status
        ]
    return filtered


def _agent_summary(agent: RunningAgentInfo) -> dict[str, Any]:
    name = agent.name or "(unnamed)"
    has_name = bool(agent.name)
    has_artifact_dir = bool(agent.artifacts_dir and Path(agent.artifacts_dir).is_dir())
    retry_lineage = _retry_lineage(agent.artifacts_dir)
    prompt = _prompt_snippet(agent.prompt)

    return {
        "name": name,
        "project": agent.project or None,
        "status": agent.status.lower(),
        "pid": _optional_uint(agent.pid),
        "model": agent.model,
        "provider": agent.provider,
        "workspace_number": _optional_uint(agent.workspace_num),
        "started_at": agent.started_at.isoformat() if agent.started_at else None,
        "duration_seconds": _optional_uint(agent.duration_seconds),
        "prompt_snippet": prompt,
        "has_artifact_dir": has_artifact_dir,
        "retry_lineage": retry_lineage,
        "actions": {
            "can_resume": has_name,
            "can_wait": has_name,
            "can_kill": has_name and agent.status.upper() == "RUNNING",
            "can_retry": has_name and has_artifact_dir,
        },
        "display": {
            "title": name,
            "subtitle": _subtitle(agent),
            "status_label": agent.status.replace("_", " ").title(),
        },
    }


def _retry_lineage(artifacts_dir: str | None) -> dict[str, Any]:
    empty = {
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "retry_attempt": None,
        "parent_agent_name": None,
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
        "retry_of_timestamp": _optional_str(data.get("retry_of_timestamp")),
        "retried_as_timestamp": _optional_str(data.get("retried_as_timestamp")),
        "retry_chain_root_timestamp": _optional_str(
            data.get("retry_chain_root_timestamp")
        ),
        "retry_attempt": _optional_uint(data.get("retry_attempt")),
        "parent_agent_name": _optional_str(data.get("parent_agent_name")),
    }


def _prompt_snippet(prompt: str | None) -> str | None:
    if prompt is None:
        return None
    prompt = prompt.replace("\n", " ").strip()
    if len(prompt) <= _PROMPT_SNIPPET_LIMIT:
        return prompt
    return prompt[:_PROMPT_SNIPPET_LIMIT]


def _subtitle(agent: RunningAgentInfo) -> str | None:
    parts = [part for part in (agent.project, agent.provider, agent.model) if part]
    return " - ".join(parts) if parts else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_uint(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _directive_name(name: str) -> str:
    if _SAFE_DIRECTIVE_NAME_RE.fullmatch(name):
        return name
    return f"`{name.replace('`', '')}`"


def _option_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "agent"
