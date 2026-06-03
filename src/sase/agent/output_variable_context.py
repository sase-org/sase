"""Jinja namespace context for cross-agent output variables."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SASE_AGENT_VAR_UPSTREAMS_ENV = "SASE_AGENT_VAR_UPSTREAMS_JSON"

_JINJA_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class _AgentOutputVariableNamespaceError(ValueError):
    """Raised when an agent output-variable namespace cannot be exposed."""


def _namespace_path_for_agent_output_variables(
    *,
    agent_name: str | None,
    agent_name_template: str | None = None,
) -> tuple[str, ...]:
    """Return the nested Jinja namespace path for an agent's output variables."""
    source = _namespace_source(agent_name=agent_name, template=agent_name_template)
    normalized = source.replace("-", "_")
    components = tuple(normalized.split("."))
    if not components or any(not component for component in components):
        raise _AgentOutputVariableNamespaceError(
            f"Invalid output-variable namespace {source!r}: empty component"
        )
    invalid = [
        component
        for component in components
        if _JINJA_IDENTIFIER_RE.fullmatch(component) is None
    ]
    if invalid:
        raise _AgentOutputVariableNamespaceError(
            "Invalid output-variable namespace "
            f"{source!r}: {invalid[0]!r} is not a valid Jinja identifier"
        )
    return components


def _namespace_source(*, agent_name: str | None, template: str | None) -> str:
    if template:
        from sase.agent.names import (
            indexed_agent_name_base,
            is_indexed_agent_name_template,
        )

        if is_indexed_agent_name_template(template):
            return indexed_agent_name_base(template)
    if agent_name:
        return agent_name
    if template:
        return template
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
    namespace_path = _namespace_path_for_agent_output_variables(
        agent_name=agent_name,
        agent_name_template=agent_name_template,
    )
    return {
        "name": agent_name,
        "namespace": ".".join(namespace_path),
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
    """Load upstream output variables as nested Jinja named-arg context."""
    context: dict[str, Any] = {}
    seen_artifacts_dirs: set[str] = set()

    for upstream in _decode_upstreams(upstreams_json):
        artifacts_dir = _upstream_artifacts_dir(upstream)
        if artifacts_dir is None:
            continue
        seen_artifacts_dirs.add(artifacts_dir)
        variables = _read_variables_if_present(artifacts_dir)
        if not variables:
            continue
        namespace = _namespace_path_from_upstream(upstream)
        _merge_namespace_variables(context, namespace, variables)

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
        namespace = _namespace_path_for_agent_output_variables(
            agent_name=agent_name,
            agent_name_template=agent_name_template,
        )
        _merge_namespace_variables(context, namespace, variables)

    return context


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


def _namespace_path_from_upstream(upstream: Mapping[str, Any]) -> tuple[str, ...]:
    namespace = upstream.get("namespace")
    if isinstance(namespace, str) and namespace:
        return _validate_namespace_string(namespace)
    name = upstream.get("name")
    template = upstream.get("agent_name_template")
    return _namespace_path_for_agent_output_variables(
        agent_name=name if isinstance(name, str) else None,
        agent_name_template=template if isinstance(template, str) else None,
    )


def _validate_namespace_string(namespace: str) -> tuple[str, ...]:
    components = tuple(namespace.split("."))
    if not components or any(not component for component in components):
        raise _AgentOutputVariableNamespaceError(
            f"Invalid output-variable namespace {namespace!r}: empty component"
        )
    invalid = [
        component
        for component in components
        if _JINJA_IDENTIFIER_RE.fullmatch(component) is None
    ]
    if invalid:
        raise _AgentOutputVariableNamespaceError(
            "Invalid output-variable namespace "
            f"{namespace!r}: {invalid[0]!r} is not a valid Jinja identifier"
        )
    return components


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


def _merge_namespace_variables(
    context: dict[str, Any],
    namespace: tuple[str, ...],
    variables: Mapping[str, str],
) -> None:
    target = context
    for component in namespace[:-1]:
        existing = target.get(component)
        if existing is None:
            child: dict[str, Any] = {}
            target[component] = child
            target = child
            continue
        if not isinstance(existing, dict):
            joined = ".".join(namespace)
            raise _AgentOutputVariableNamespaceError(
                f"Output-variable namespace {joined!r} collides with a value"
            )
        target = existing

    leaf = namespace[-1]
    existing_leaf = target.get(leaf)
    if existing_leaf is None:
        target[leaf] = dict(variables)
        return
    if not isinstance(existing_leaf, dict):
        joined = ".".join(namespace)
        raise _AgentOutputVariableNamespaceError(
            f"Output-variable namespace {joined!r} collides with a value"
        )
    existing_leaf.update(variables)


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
    "SASE_AGENT_VAR_UPSTREAMS_ENV",
    "build_agent_output_variable_context",
    "build_agent_var_upstream_record",
    "encode_agent_var_upstreams",
]
