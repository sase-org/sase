"""Shared helpers for agent revival."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.agent_artifact_paths import resolve_agent_artifact_path

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType


def is_child_of(child: Agent, parent: Agent) -> bool:
    """Check if *child* is a workflow step, follow-up, or retry of *parent*.

    Matches workflow step children (``parent_workflow`` set), follow-up
    agents like ``--code`` / ``--1`` (``parent_timestamp`` set,
    ``parent_workflow`` is None), and spawn-on-retry children
    (``retry_of_timestamp`` set).
    """
    # Spawn-on-retry: retry children link to the failing parent via
    # retry_of_timestamp (they are otherwise top-level RUNNING agents).
    if (
        child.retry_of_timestamp
        and parent.raw_suffix
        and child.retry_of_timestamp == parent.raw_suffix
    ):
        return True
    if not child.is_workflow_child or child.parent_timestamp != parent.raw_suffix:
        return False
    # Workflow step children have parent_workflow set; follow-up agents do not.
    return child.parent_workflow is None or child.parent_workflow == parent.workflow


def merge_dismissed_agents(
    in_memory: Iterable[Agent],
    archive: Iterable[Agent],
) -> list[Agent]:
    """Merge same-session dismissed rows with archive rows, preserving order."""
    merged: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    for agent in (*list(in_memory), *list(archive)):
        if agent.identity in seen:
            continue
        merged.append(agent)
        seen.add(agent.identity)
    return merged


def revived_artifact_dir(
    agent: Agent,
    *,
    parent_artifacts_dir: str | None = None,
) -> str | None:
    artifact_dir = (
        parent_artifacts_dir or agent.artifacts_dir or agent.get_artifacts_dir()
    )
    if not artifact_dir:
        return None
    return str(resolve_agent_artifact_path(artifact_dir))


def schedule_revive_full_history_refresh(
    app: Any,
    *,
    reason: str,
    on_complete: Callable[[], None],
) -> None:
    """Schedule a revive full-history refresh across app/test scheduler shapes."""
    schedule = app._schedule_agents_async_refresh
    kwargs: dict[str, Any] = {
        "full_history": True,
        "on_complete": on_complete,
    }
    if "full_history_reason" in inspect.signature(schedule).parameters:
        kwargs["full_history_reason"] = reason
    schedule(**kwargs)


def schedule_revive_artifact_delta_refresh(
    app: Any,
    artifact_dirs: Iterable[str | Path | None],
    *,
    reason: str,
    on_complete: Callable[[], None],
) -> bool:
    """Schedule a known-dir revive delta, falling back to full history."""
    paths = [Path(path) for path in artifact_dirs if path is not None]
    if not paths:
        schedule_revive_full_history_refresh(
            app,
            reason=reason,
            on_complete=on_complete,
        )
        return False

    schedule_delta = getattr(app, "_schedule_agent_artifact_delta_refresh", None)
    if not callable(schedule_delta):
        schedule_revive_full_history_refresh(
            app,
            reason=reason,
            on_complete=on_complete,
        )
        return False

    if "on_complete" not in inspect.signature(schedule_delta).parameters:
        schedule_revive_full_history_refresh(
            app,
            reason=reason,
            on_complete=on_complete,
        )
        return False

    kwargs: dict[str, Any] = {"source": reason}
    kwargs["on_complete"] = on_complete
    schedule_delta(paths, **kwargs)
    return True
