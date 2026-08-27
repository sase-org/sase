"""Artifact-file resolution and content retrieval for Agent instances."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agent.artifact_files_cache import get_global_cache
from sase.ace.tui.models.agent import AgentType
from sase.core.agent_artifact_paths import (
    resolve_agent_artifact_path,
    resolve_agent_artifact_timestamp_path,
)

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent


def _is_monitor_claim_workflow(workflow: str) -> bool:
    """Return whether *workflow* is a monitor's workspace-claim label.

    Imported lazily: ``sase.monitor`` initializes the whole monitor
    supervisor stack, and this module sits on the TUI's hot agent-loader
    path where most calls never reach this branch.
    """
    from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW

    return workflow == MONITOR_WORKSPACE_CLAIM_WORKFLOW


def get_artifacts_dir(agent: Agent) -> str | None:
    """Get the artifacts directory path for this agent.

    Returns:
        Path to the artifacts directory, or None if it cannot be determined.
    """
    # If we have an explicit artifacts_dir (from marker files), resolve it in
    # case persisted state still points at the legacy flat layout.
    if agent.artifacts_dir:
        resolved = resolve_agent_artifact_path(agent.artifacts_dir)
        if resolved.is_dir():
            return str(resolved)

    # Extract project name from project_file
    # Format: ~/.sase/projects/<project>/<project>.sase (or legacy .gp)
    project_path = Path(agent.project_file)
    project_name = project_path.parent.name

    # Determine workflow name based on agent type
    if agent.agent_type == AgentType.RUNNING:
        workflow = agent.workflow or "run"
        # Extract base workflow: "ace(run)-timestamp" -> "ace-run"
        if workflow.startswith("ace(run)"):
            workflow_name = "ace-run"
        elif workflow.startswith("axe(fix-hook)"):
            workflow_name = "fix-hook"
        elif workflow.startswith("axe(crs)"):
            workflow_name = "crs"
        elif workflow.startswith("axe(mentor)"):
            # "axe(mentor)-complete-TIMESTAMP" -> "mentor-complete"
            parts = workflow.split("-")
            workflow_name = f"mentor-{parts[1]}" if len(parts) >= 2 else "mentor"
        elif workflow.startswith("mentor(") and workflow.endswith(")"):
            # "mentor(code_quality)" -> artifacts dir "mentor-code_quality"
            profile = workflow[7:-1]
            workflow_name = f"mentor-{profile}"
        elif workflow == "mentor" and agent.mentor_name:
            # Patch-sourced mentor: workflow="mentor", mentor_name="code_quality"
            # -> artifacts dir "mentor-code_quality"
            workflow_name = f"mentor-{agent.mentor_name}"
        elif workflow == "fix_hook":
            # VCS workspace claim uses "fix_hook" (from xprompt
            # workflow_label) but artifacts dir is "fix-hook"
            workflow_name = "fix-hook"
        elif _is_monitor_claim_workflow(workflow):
            # A monitor's workspace claim uses a distinct workflow label
            # (see sase.monitor.claims) so the starter's runner-exit cleanup
            # cannot release it, but its artifacts live alongside the
            # ordinary ace-run agent it is monitoring.
            workflow_name = "ace-run"
        else:
            workflow_name = workflow
    elif agent.agent_type == AgentType.WORKFLOW:
        # Workflow artifacts: workflow-{name}, or ace-run for appears_as_agent
        if agent.workflow:
            base_workflow = (
                agent.workflow.split("/")[-1]
                if "/" in agent.workflow
                else agent.workflow
            )
            # appears_as_agent workflows may use ace-run/ artifacts dir
            if agent.appears_as_agent:
                timestamp = extract_artifacts_timestamp(agent)
                if timestamp:
                    candidate = resolve_agent_artifact_timestamp_path(
                        project_name,
                        "ace-run",
                        timestamp,
                    )
                    if candidate.is_dir():
                        return str(candidate)
            workflow_name = f"workflow-{base_workflow}"
        else:
            return None
    else:
        return None

    # Extract and convert timestamp from raw_suffix
    # raw_suffix format: <agent>-<PID>-YYmmdd_HHMMSS or similar
    # artifacts_dir expects: YYYYmmddHHMMSS
    if agent.raw_suffix is None:
        return None

    timestamp = extract_artifacts_timestamp(agent)
    if timestamp is None:
        return None

    artifacts_dir = resolve_agent_artifact_timestamp_path(
        project_name,
        workflow_name,
        timestamp,
    )

    if artifacts_dir.is_dir():
        return str(artifacts_dir)

    return None


def extract_artifacts_timestamp(agent: Agent) -> str | None:
    """Extract and convert timestamp from raw_suffix to artifacts format.

    For RUNNING agents: raw_suffix is already YYYYmmddHHMMSS (14 chars)
    For Patch-sourced agents: raw_suffix uses YYmmdd_HHMMSS format (13 chars with underscore)
    artifacts_dir expects: YYYYmmddHHMMSS format (14 chars, no underscore)

    Returns:
        Converted timestamp string, or None if parsing fails.
    """
    if agent.raw_suffix is None:
        return None

    # For RUNNING agents, raw_suffix is the timestamp directly (14 chars)
    if len(agent.raw_suffix) == 14 and agent.raw_suffix.isdigit():
        return agent.raw_suffix

    # Extract timestamp part from suffix
    ts: str | None = None

    if "-" in agent.raw_suffix:
        parts = agent.raw_suffix.split("-")
        if len(parts) >= 2:
            ts = parts[-1]
    else:
        ts = agent.raw_suffix

    # Validate and convert format: YYmmdd_HHMMSS -> YYYYmmddHHMMSS
    if ts and len(ts) == 13 and ts[6] == "_":
        # Add century prefix and remove underscore
        return f"20{ts[:6]}{ts[7:]}"

    return None


def get_raw_xprompt_content(agent: Agent) -> str | None:
    """Get the raw xprompt content (before preprocessing/expansion).

    Returns:
        Raw xprompt content string, or None if not available.
    """
    try:
        artifacts_dir = agent.get_artifacts_dir()
    except AttributeError:
        return None
    if artifacts_dir is None:
        return None
    raw_path = os.path.join(artifacts_dir, "raw_xprompt.md")
    return get_global_cache().read_text(raw_path)


def get_restartable_prompt_content(
    agent: Agent,
    agents: Sequence[Agent] = (),
) -> str | None:
    """Return a complete prompt suitable for restarting *agent*.

    ``raw_xprompt.md`` is authoritative. Historical plan-chain members may
    lack it, so their cached detail-panel ``*_prompt.md`` selection is used as
    a body and any consumed launch context is reconstructed from already-loaded
    row metadata and ancestor artifacts.

    This helper performs filesystem work and must be called off the Textual
    message pump.
    """
    raw_prompt = agent.get_raw_xprompt_content()
    if raw_prompt is not None:
        return raw_prompt

    try:
        artifacts_dir = agent.get_artifacts_dir()
    except AttributeError:
        return None
    if artifacts_dir is None:
        return None
    cache = get_global_cache()
    selected = cache.select_prompt_file(
        artifacts_dir,
        is_workflow_child=agent.is_workflow_child,
        step_name=agent.step_name,
    )
    if selected is None:
        return None
    body = cache.read_text(selected)
    if body is None:
        return None

    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    existing_vcs = extract_vcs_workflow_tag(body) or find_vcs_workflow_tag(body)
    vcs_tag = existing_vcs or _restart_vcs_tag(agent, agents)

    prefixes: list[str] = []
    if not _has_model_directive(body):
        model_directive = _restart_model_directive(agent)
        if model_directive:
            prefixes.append(model_directive)
    if existing_vcs is None and vcs_tag:
        prefixes.append(vcs_tag.strip())

    rebuilt = "\n".join([*prefixes, body]) if prefixes else body
    rollover_refs = _restart_rollover_refs(agent, agents, vcs_tag)
    if rollover_refs and rollover_refs.strip() not in rebuilt:
        rebuilt = f"{rebuilt.rstrip()}\n{rollover_refs.strip()}\n"
    return rebuilt


def _has_model_directive(prompt: str) -> bool:
    try:
        from sase.xprompt.directives import has_model_directive

        return has_model_directive(prompt)
    except Exception:
        return False


def _restart_model_directive(agent: Agent) -> str:
    model = (agent.model or "").strip()
    if not model:
        return ""

    from sase.xprompt.effort import split_model_effort

    model, embedded_effort = split_model_effort(model)
    provider = (agent.llm_provider or "").strip()
    if provider and "/" not in model:
        model = f"{provider}/{model}"
    effort = (agent.reasoning_effort or embedded_effort or "").strip()
    if effort:
        model = f"{model}@{effort}"

    if any(char.isspace() or char in ",()=" for char in model):
        return f"%model({json.dumps(model)})"
    return f"%model:{model}"


def _restart_vcs_tag(agent: Agent, agents: Sequence[Agent]) -> str | None:
    try:
        from sase.ace.tui.actions.agents._fork_scope import resolve_vcs_tag

        prompt_name = agent.presented_agent_name or agent.agent_name or agent.cl_name
        return resolve_vcs_tag(agent, prompt_name, agents)
    except Exception:
        return None


def _restart_rollover_refs(
    agent: Agent,
    agents: Sequence[Agent],
    vcs_tag: str | None,
) -> str:
    from sase.axe.run_agent_exec_plan_artifacts import (
        embedded_workflow_refs_from_metadata,
    )

    cache = get_global_cache()
    for candidate in _agent_and_ancestors(agent, agents):
        artifacts_dir = get_artifacts_dir(candidate)
        if artifacts_dir is None:
            continue
        metadata = cache.read_json(
            os.path.join(artifacts_dir, "embedded_workflows.json")
        )
        refs = embedded_workflow_refs_from_metadata(metadata, vcs_tag)
        if refs:
            return refs
    return ""


def _agent_and_ancestors(
    agent: Agent,
    agents: Sequence[Agent],
) -> list[Agent]:
    by_timestamp = {
        candidate.raw_suffix: candidate
        for candidate in agents
        if candidate.raw_suffix is not None
    }
    result = [agent]
    seen = {agent.identity}
    current = agent
    while current.parent_timestamp:
        parent = by_timestamp.get(current.parent_timestamp)
        if parent is None or parent.identity in seen:
            break
        result.append(parent)
        seen.add(parent.identity)
        current = parent
    return result


def get_live_reply_content(agent: Agent) -> str | None:
    """Get the live reply content for running agents.

    Returns:
        Live reply content string, or None if not available.
    """
    if agent.is_gate and agent.gate_output_path:
        return get_global_cache().read_live_reply(
            os.path.expanduser(agent.gate_output_path)
        )
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None
    path = os.path.join(artifacts_dir, "live_reply.md")
    return get_global_cache().read_live_reply(path)


def get_timestamped_reply_chunks(agent: Agent) -> list[tuple[str, str]] | None:
    """Load live reply split into timestamped chunks.

    Returns:
        List of (iso_timestamp, content_text) tuples, or None if timestamps
        unavailable. Falls back to None so callers can use the un-timestamped
        path.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None

    timestamps_path = os.path.join(artifacts_dir, "live_reply_timestamps.jsonl")
    reply_path = os.path.join(artifacts_dir, "live_reply.md")
    return get_global_cache().read_reply_chunks(timestamps_path, reply_path)


def get_response_content(agent: Agent) -> str | None:
    """Get the response content for DONE agents.

    Returns:
        Response content string, or None if not available.
    """
    if agent.response_path is None:
        return None
    return get_global_cache().read_text(os.path.expanduser(agent.response_path))


def get_chat_response_content(agent: Agent) -> str | None:
    """Get response content from agent_meta.json chat_path.

    Fallback for agents where the live reply and response path are empty
    (e.g., agents killed during the plan phase before any reply was written).

    Returns:
        Chat response content string, or None if not available.
    """
    artifacts_dir = get_artifacts_dir(agent)
    if artifacts_dir is None:
        return None
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    data = get_global_cache().read_json(meta_path)
    if not isinstance(data, dict):
        return None
    chat_path = data.get("chat_path")
    if not isinstance(chat_path, str) or not chat_path:
        return None
    return get_global_cache().read_text(os.path.expanduser(chat_path))
