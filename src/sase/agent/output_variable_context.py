"""Jinja ``agents`` context for cross-agent output variables."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SASE_AGENT_VAR_UPSTREAMS_ENV = "SASE_AGENT_VAR_UPSTREAMS_JSON"

# Single top-level Jinja variable holding every producer's output variables,
# keyed by agent name. Reserved in the agent-run Jinja named-arg namespace.
AGENTS_CONTEXT_KEY = "agents"


class _AgentOutputVariableNamespaceError(ValueError):
    """Raised when an agent output-variable key cannot be derived."""


def _agent_key_for_output_variables(
    *,
    agent_name: str | None,
    agent_name_template: str | None = None,
) -> str:
    """Return the stable ``agents`` dictionary key for an agent's variables.

    The key is the agent's stable reference so that xprompts stay authorable
    and repeatable across runs:

    - An indexed template (``build-@``) yields its base (``build``), not the
      launch-time ``build-1`` allocated at runtime.
    - Otherwise the concrete/dotted agent name is used verbatim
      (``research.final``, ``0n.cld``), without any Jinja-identifier munging.
    """
    if agent_name_template:
        from sase.agent.names import (
            indexed_agent_name_base,
            is_indexed_agent_name_template,
        )

        if is_indexed_agent_name_template(agent_name_template):
            return indexed_agent_name_base(agent_name_template)
    if agent_name:
        return agent_name
    if agent_name_template:
        return agent_name_template
    raise _AgentOutputVariableNamespaceError(
        "Cannot expose output variables without an agent name"
    )


def build_agent_var_upstream_record(
    *,
    agent_name: str,
    project_name: str,
    workflow_timestamp: str,
    agent_name_template: str | None = None,
) -> dict[str, Any]:
    """Build the launch-scoped upstream record passed to later agents."""
    agent_key = _agent_key_for_output_variables(
        agent_name=agent_name,
        agent_name_template=agent_name_template,
    )
    return {
        "name": agent_name,
        "agent_key": agent_key,
        "agent_name_template": agent_name_template,
        "project_name": project_name,
        "workflow_timestamp": workflow_timestamp,
        "artifacts_dir": _artifacts_dir_for_launch(project_name, workflow_timestamp),
    }


def encode_agent_var_upstreams(upstreams: Sequence[Mapping[str, Any]]) -> str:
    """Serialize upstream records for ``SASE_AGENT_VAR_UPSTREAMS_JSON``."""
    return json.dumps(list(upstreams), sort_keys=True, separators=(",", ":"))


def build_agent_output_variable_context(
    *,
    upstreams_json: str | None,
    wait_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Load upstream output variables under the single ``agents`` named arg.

    Returns ``{"agents": {agent_key: variables, ...}}`` when any producer wrote
    variables, else ``{}`` (so nothing is injected when there is nothing to
    render). Later producers override earlier ones for the same key.
    """
    agents: dict[str, dict[str, str]] = {}
    seen_artifacts_dirs: set[str] = set()

    for upstream in _decode_upstreams(upstreams_json):
        artifacts_dir = _upstream_artifacts_dir(upstream)
        if artifacts_dir is None:
            continue
        seen_artifacts_dirs.add(artifacts_dir)
        variables = _read_variables_if_present(artifacts_dir)
        if not variables:
            continue
        key = _agent_key_from_upstream(upstream)
        _merge_agent_variables(agents, key, variables)

    for wait_name in wait_names:
        resolved = _resolve_waited_agent(wait_name)
        if resolved is None:
            continue
        artifacts_dir, agent_name, agent_name_template = resolved
        if artifacts_dir in seen_artifacts_dirs:
            continue
        variables = _read_variables_if_present(artifacts_dir)
        if not variables:
            continue
        key = _agent_key_for_output_variables(
            agent_name=agent_name,
            agent_name_template=agent_name_template,
        )
        _merge_agent_variables(agents, key, variables)

    if not agents:
        return {}
    return {AGENTS_CONTEXT_KEY: agents}


def _decode_upstreams(upstreams_json: str | None) -> list[dict[str, Any]]:
    if not upstreams_json:
        return []
    try:
        loaded = json.loads(upstreams_json)
    except json.JSONDecodeError as exc:
        raise _AgentOutputVariableNamespaceError(
            f"Invalid {SASE_AGENT_VAR_UPSTREAMS_ENV}: {exc.msg}"
        ) from exc
    if not isinstance(loaded, list):
        raise _AgentOutputVariableNamespaceError(
            f"Invalid {SASE_AGENT_VAR_UPSTREAMS_ENV}: expected a list"
        )
    return [item for item in loaded if isinstance(item, dict)]


def _upstream_artifacts_dir(upstream: Mapping[str, Any]) -> str | None:
    artifacts_dir = upstream.get("artifacts_dir")
    if isinstance(artifacts_dir, str) and artifacts_dir:
        return artifacts_dir
    project_name = upstream.get("project_name")
    timestamp = upstream.get("workflow_timestamp")
    if isinstance(project_name, str) and isinstance(timestamp, str):
        return _artifacts_dir_for_launch(project_name, timestamp)
    return None


def _agent_key_from_upstream(upstream: Mapping[str, Any]) -> str:
    """Derive the ``agents`` key from an upstream record.

    Tolerates older payloads (in-flight spawned agents) that may only carry
    ``name``/``agent_name_template`` by deriving the key from the best
    available fields. A legacy ``namespace`` field is ignored.
    """
    agent_key = upstream.get("agent_key")
    if isinstance(agent_key, str) and agent_key:
        return agent_key
    name = upstream.get("name")
    template = upstream.get("agent_name_template")
    return _agent_key_for_output_variables(
        agent_name=name if isinstance(name, str) else None,
        agent_name_template=template if isinstance(template, str) else None,
    )


def _read_variables_if_present(artifacts_dir: str) -> dict[str, str]:
    from sase.core.agent_output_variables import read_agent_output_variables

    try:
        return read_agent_output_variables(artifacts_dir)
    except OSError:
        return {}


def _resolve_waited_agent(
    wait_name: str,
) -> tuple[str, str, str | None] | None:
    from sase.agent.names import resolve_resume_agent_name
    from sase.core.agent_artifact_helpers import read_json_object

    agent = resolve_resume_agent_name(wait_name)
    if agent is None:
        return None
    artifacts_dir = agent.artifacts_dir
    meta = read_json_object(Path(artifacts_dir) / "agent_meta.json")
    meta_name = meta.get("name")
    template = meta.get("agent_name_template")
    return (
        artifacts_dir,
        meta_name if isinstance(meta_name, str) and meta_name else agent.name,
        template if isinstance(template, str) and template else None,
    )


def _merge_agent_variables(
    agents: dict[str, dict[str, str]],
    key: str,
    variables: Mapping[str, str],
) -> None:
    """Merge ``variables`` into ``agents[key]``, later writes overriding."""
    existing = agents.get(key)
    if existing is None:
        agents[key] = dict(variables)
        return
    existing.update(variables)


def _artifacts_dir_for_launch(project_name: str, workflow_timestamp: str) -> str:
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.core.paths import sase_projects_dir

    artifacts_timestamp = convert_timestamp_to_artifacts_format(workflow_timestamp)
    return str(
        sase_projects_dir()
        / project_name
        / "artifacts"
        / "ace-run"
        / artifacts_timestamp
    )


__all__ = [
    "AGENTS_CONTEXT_KEY",
    "SASE_AGENT_VAR_UPSTREAMS_ENV",
    "build_agent_output_variable_context",
    "build_agent_var_upstream_record",
    "encode_agent_var_upstreams",
]
