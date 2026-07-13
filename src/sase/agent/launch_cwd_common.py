"""Shared helpers for CWD-based agent launches."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sase.agent.launch_validation import internal_agent_name_bypass_enabled
from sase.core.paths import sase_projects_dir


@dataclass(frozen=True)
class _KnownProjectVcsLaunchRef:
    workflow_type: str
    ref: str
    workspace_dir: str
    project_file: str


def internal_agent_name_bypass_for_launch(
    extra_env: dict[str, str] | None,
    segment_extra_env: Sequence[dict[str, str] | None] | None = None,
) -> bool:
    if internal_agent_name_bypass_enabled(extra_env):
        return True
    if segment_extra_env is None:
        return False
    return all(internal_agent_name_bypass_enabled(env) for env in segment_extra_env)


_PLANNED_AGENT_NAME_ENV = "SASE_AGENT_PLANNED_NAME"


def _future_agent_artifacts_dir(*, project_name: str, timestamp: str) -> str:
    from sase.artifacts import convert_timestamp_to_artifacts_format
    from sase.core.agent_artifact_paths import canonical_agent_artifact_path

    return str(
        canonical_agent_artifact_path(
            project_name,
            "ace-run",
            convert_timestamp_to_artifacts_format(timestamp),
        )
    )


def plan_single_agent_name(
    query: str,
    extra_env: dict[str, str] | None,
    *,
    project_name: str,
    timestamp: str,
) -> tuple[dict[str, str] | None, Any | None]:
    """Allocate a parent-side agent name for a single-prompt launch.

    Returns ``extra_env`` augmented with ``SASE_AGENT_PLANNED_NAME`` when the
    name is safely knowable in the parent (explicit ``%name:`` or
    unambiguous auto-allocation). Leaves *extra_env* unchanged when the
    caller already chose a name, or when the prompt's name depends on
    xprompt expansion that only the child can perform.
    """
    if extra_env and _PLANNED_AGENT_NAME_ENV in extra_env:
        return extra_env, None

    from sase.agent.multi_prompt_references import PlannedNameAllocator

    allocator = PlannedNameAllocator()
    planned_name, _ = allocator.planned_name_for_prompt(
        query,
        artifacts_dir=_future_agent_artifacts_dir(
            project_name=project_name,
            timestamp=timestamp,
        ),
    )
    if planned_name is None:
        return extra_env, allocator

    augmented = dict(extra_env or {})
    augmented[_PLANNED_AGENT_NAME_ENV] = planned_name
    return augmented, allocator


def resolve_known_project_vcs_launch_ref(
    prompt: str,
) -> _KnownProjectVcsLaunchRef | None:
    """Resolve a generic VCS ref that points at a known project checkout."""
    from pathlib import Path

    from sase.agent.launch_projects import (
        enable_known_project_for_launch_ref,
        extract_known_project_vcs_launch_ref,
    )
    from sase.xprompt._parsing import resolve_known_project_ref
    from sase.xprompt.loader import get_known_project_workspaces

    known_ref = extract_known_project_vcs_launch_ref(prompt)
    if known_ref is None:
        return None

    workflow_type, ref = known_ref
    enable_known_project_for_launch_ref(ref)
    known_projects = get_known_project_workspaces()
    project_name = resolve_known_project_ref(ref, known_projects)
    if project_name is None:
        return None
    workspace_dir = known_projects.get(project_name)
    if workspace_dir is None:
        return None

    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    return _KnownProjectVcsLaunchRef(
        workflow_type=workflow_type,
        ref=project_name,
        workspace_dir=str(workspace_dir),
        project_file=str(project_file),
    )
