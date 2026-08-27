"""Helpers for on-demand hydration of projected artifact-index records."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    load_agent_artifact_records,
)
from sase.core.agent_scan_wire import AgentArtifactRecordWire, PromptStepMarkerWire

from .agent_types import AgentType, LinkedRepoMetadata
from ._loaders._meta_enrichment_common import parse_linked_repos

if TYPE_CHECKING:
    from .agent import Agent

log = logging.getLogger(__name__)

_HYDRATION_ATTEMPTED_ATTR = "_projected_record_hydration_attempted"
_HYDRATION_PENDING_ATTR = "_projected_record_hydration_pending"


def resolve_step_output(agent: Agent) -> dict[str, Any] | None:
    """Return the currently hydrated step output without doing blocking work."""

    return agent.step_output if isinstance(agent.step_output, dict) else None


def resolve_linked_repos(
    agent: Agent,
    *,
    hydrate: bool = False,
) -> tuple[LinkedRepoMetadata, ...]:
    """Return linked repositories, optionally hydrating a projected record first."""

    if hydrate and projected_agent_needs_hydration(agent):
        hydrate_projected_agent(agent)
    return agent.linked_repos


def projected_agent_needs_hydration(agent: Agent) -> bool:
    """Return True when *agent* is a list-shaped index record needing hydration."""

    return projected_agent_waiting_for_hydration(agent) and not bool(
        getattr(agent, _HYDRATION_PENDING_ATTR, False)
    )


def projected_agent_waiting_for_hydration(agent: Agent) -> bool:
    """Return True while detail rendering should wait for full-record hydration."""

    return (
        agent.record_shape == "list"
        and bool(agent.index_record_dir)
        and not bool(getattr(agent, _HYDRATION_ATTEMPTED_ATTR, False))
    )


def mark_projected_agent_hydration_pending(agent: Agent, pending: bool) -> None:
    """Mark an agent's projected-record hydration worker state."""

    setattr(agent, _HYDRATION_PENDING_ATTR, bool(pending))


def mark_projected_agent_hydration_attempted(agent: Agent) -> None:
    """Prevent repeated synchronous fallbacks after one failed hydration."""

    setattr(agent, _HYDRATION_ATTEMPTED_ATTR, True)


def hydrate_projected_agent(agent: Agent) -> bool:
    """Load and apply the full index record for one projected agent.

    This function may block on SQLite and must be called from a worker thread
    when used by the TUI detail render path.
    """

    artifact_dir = agent.index_record_dir
    if agent.record_shape != "list" or not artifact_dir:
        return False

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        mark_projected_agent_hydration_attempted(agent)
        return False

    try:
        records = load_agent_artifact_records(index_path, [artifact_dir])
    except (ImportError, AttributeError, OSError, RuntimeError, ValueError):
        log.debug(
            "projected record hydration failed for %s", artifact_dir, exc_info=True
        )
        mark_projected_agent_hydration_attempted(agent)
        return False

    if not records:
        mark_projected_agent_hydration_attempted(agent)
        return False

    _apply_full_record(agent, records[0])
    agent.record_shape = "full"
    mark_projected_agent_hydration_attempted(agent)
    return True


def _apply_full_record(agent: Agent, record: AgentArtifactRecordWire) -> bool:
    changed = False
    output = _full_step_output_for_agent(agent, record)
    if output is not None:
        merged = _merge_step_output(agent.step_output, output)
        if merged != agent.step_output:
            agent.step_output = merged
            changed = True

    if record.agent_meta is not None:
        linked_repos = parse_linked_repos(record.agent_meta.linked_repos)
        if linked_repos != agent.linked_repos:
            agent.linked_repos = linked_repos
            changed = True

    if record.artifact_dir and record.artifact_dir != agent.index_record_dir:
        agent.index_record_dir = record.artifact_dir
        changed = True

    return changed


def _full_step_output_for_agent(
    agent: Agent,
    record: AgentArtifactRecordWire,
) -> dict[str, Any] | None:
    if agent.is_workflow_child:
        step = _matching_prompt_step(agent, record)
        return step.output if step is not None else None

    if agent.agent_type is AgentType.WORKFLOW and record.workflow_state is not None:
        for workflow_step in reversed(record.workflow_state.steps):
            if isinstance(workflow_step.output, dict):
                return workflow_step.output
        return None

    if record.done is not None and isinstance(record.done.step_output, dict):
        return record.done.step_output
    return None


def _matching_prompt_step(
    agent: Agent,
    record: AgentArtifactRecordWire,
) -> PromptStepMarkerWire | None:
    if agent.prompt_step_file_name:
        for step in record.prompt_steps:
            if step.file_name == agent.prompt_step_file_name:
                return step

    for step in record.prompt_steps:
        if step.step_index == agent.step_index and step.step_name == agent.step_name:
            return step
    return None


def _merge_step_output(
    existing: dict[str, Any] | None,
    loaded: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(loaded)
    if isinstance(existing, dict):
        for key, value in existing.items():
            merged.setdefault(key, value)
    return merged


__all__ = [
    "hydrate_projected_agent",
    "mark_projected_agent_hydration_attempted",
    "mark_projected_agent_hydration_pending",
    "projected_agent_needs_hydration",
    "projected_agent_waiting_for_hydration",
    "resolve_linked_repos",
    "resolve_step_output",
]
