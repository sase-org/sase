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

    - An agent-name template (``build-@``) yields its base (``build``), not the
      launch-time ``build-0`` allocated at runtime.
    - Otherwise the concrete/dotted agent name is used verbatim
      (``research.final``, ``0n.cld``), without any Jinja-identifier munging.
    """
    if agent_name_template:
        from sase.agent.names import (
            agent_name_template_base,
            is_agent_name_template,
        )

        if is_agent_name_template(agent_name_template):
            return agent_name_template_base(agent_name_template)
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
        variables = _variables_with_plan_file(artifacts_dir)
        if not variables:
            continue
        key = _agent_key_from_upstream(upstream)
        _merge_agent_variables(agents, key, variables)

    for wait_name in wait_names:
        # Submitted planner rows have no done.json, so they are resolved
        # separately and keyed by their canonical ``<base>--plan`` row name.
        plan_resolved = _resolve_submitted_plan_wait(wait_name)
        if plan_resolved is not None:
            artifacts_dir, plan_key = plan_resolved
            plan_variables = _variables_with_plan_file(artifacts_dir)
            if plan_variables:
                _merge_agent_variables(agents, plan_key, plan_variables)
            continue

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


def _variables_with_plan_file(artifacts_dir: str) -> dict[str, str]:
    """Return stored output variables plus a synthesized ``plan_file`` entry.

    When *artifacts_dir* is a submitted-and-waiting planner row, the proposed
    plan path is exposed under ``plan_file`` in the producer's namespace. An
    explicit ``sase var set plan_file=...`` still wins, so previously stored
    output variables are never lost.
    """
    from sase.core.wait_dependency_resolution import submitted_plan_artifact_for_dir

    variables = _read_variables_if_present(artifacts_dir)
    plan_artifact = submitted_plan_artifact_for_dir(artifacts_dir)
    if plan_artifact is None:
        return variables
    return {"plan_file": plan_artifact.plan_path, **variables}


def _resolve_submitted_plan_wait(wait_name: str) -> tuple[str, str] | None:
    """Resolve a planner-row ``%wait`` to its artifact dir and Jinja key.

    Submitted-and-waiting planner rows have no ``done.json``, so
    :func:`resolve_resume_agent_name` cannot see them. Scan ace-run artifacts
    for a submitted planner whose canonical ``<base>--plan`` row name matches
    *wait_name* (canonical or legacy spelling) and return its
    ``(artifacts_dir, planner_row_name)``. Returns ``None`` when *wait_name* is
    not a planner-row reference or no submitted planner matches.
    """
    from sase.plan_chain import planner_row_name

    target = planner_row_name(wait_name, include_legacy_dash=True)
    if target is None:
        return None

    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
    from sase.core.paths import sase_projects_dir
    from sase.core.wait_dependency_resolution import submitted_plan_artifact

    projects_root = sase_projects_dir()
    if not projects_root.exists():
        return None
    snapshot = scan_agent_artifacts(
        projects_root,
        AgentArtifactScanOptionsWire(
            only_workflow_dirs=("ace-run",),
            include_prompt_step_markers=False,
            include_raw_prompt_snippets=False,
        ),
    )

    best_dir: str | None = None
    best_timestamp = ""
    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        meta = record.agent_meta
        if meta is None:
            continue
        plan_artifact = submitted_plan_artifact(
            meta=_plan_meta_from_wire(meta),
            plan_path_marker=(
                record.plan_path.plan_path if record.plan_path is not None else None
            ),
            outcome=record.done.outcome if record.done is not None else None,
        )
        if plan_artifact is None or plan_artifact.planner_row_name != target:
            continue
        if record.timestamp > best_timestamp:
            best_timestamp = record.timestamp
            best_dir = record.artifact_dir
    if best_dir is None:
        return None
    return best_dir, target


def _plan_meta_from_wire(meta: Any) -> dict[str, Any]:
    """Project the wire ``agent_meta`` fields the plan classifier consults."""
    return {
        "name": meta.name,
        "role_suffix": meta.role_suffix,
        "plan_submitted_at": meta.plan_submitted_at,
        "feedback_submitted_at": meta.feedback_submitted_at,
        "plan_approved": meta.plan_approved,
        "plan_path": meta.plan_path,
    }


def read_waited_agent_output_variables(wait_name: str) -> dict[str, str] | None:
    """Return a waited agent's output variables, or ``None`` if unresolvable.

    Resolves *wait_name* the same way :func:`build_agent_output_variable_context`
    does (newest matching producer generation) and reads its stored
    ``output_variables``.  Returns an empty mapping when the producer resolves
    but has written no variables, and ``None`` when no producer matches.
    """
    resolved = _resolve_waited_agent(wait_name)
    if resolved is None:
        return None
    artifacts_dir = resolved[0]
    return _read_variables_if_present(artifacts_dir)


def _resolve_waited_agent(
    wait_name: str,
) -> tuple[str, str, str | None] | None:
    from sase.agent.names import resolve_resume_agent_name
    from sase.core.artifact_file_helpers import read_json_object

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
    from sase.core.agent_artifact_paths import canonical_agent_artifact_path

    artifacts_timestamp = convert_timestamp_to_artifacts_format(workflow_timestamp)
    return str(
        canonical_agent_artifact_path(project_name, "ace-run", artifacts_timestamp)
    )


__all__ = [
    "AGENTS_CONTEXT_KEY",
    "SASE_AGENT_VAR_UPSTREAMS_ENV",
    "build_agent_output_variable_context",
    "build_agent_var_upstream_record",
    "encode_agent_var_upstreams",
    "read_waited_agent_output_variables",
]
