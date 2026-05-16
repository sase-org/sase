"""Aggregate TUI agents from changespec and artifact sources."""

from collections.abc import Callable

from sase.core.agent_scan_wire import AgentArtifactScanWire

from ...changespec import ChangeSpec
from .agent import Agent


def load_agents_from_all_sources(
    *,
    changespec_snapshot: list[ChangeSpec] | None,
    artifact_snapshot: AgentArtifactScanWire | None,
    get_all_project_files_fn: Callable[[], list[str]],
    find_all_changespecs_fn: Callable[[], list[ChangeSpec]],
    scan_artifacts_for_loader_fn: Callable[[], AgentArtifactScanWire],
    load_agents_from_running_field_fn: Callable[
        [list[str], dict[str, str | None], dict[str, str | None]], list[Agent]
    ],
    load_done_agents_from_snapshot_fn: Callable[
        [AgentArtifactScanWire, dict[str, str | None], dict[str, str | None]],
        list[Agent],
    ],
    load_running_home_agents_from_snapshot_fn: Callable[
        [AgentArtifactScanWire], list[Agent]
    ],
    load_workflow_agent_steps_from_snapshot_fn: Callable[
        [AgentArtifactScanWire], tuple[list[Agent], dict[str, dict[str, str]]]
    ],
    load_workflow_agents_from_snapshot_fn: Callable[..., list[Agent]],
    load_agents_from_hooks_fn: Callable[
        [ChangeSpec, str | None, str | None], list[Agent]
    ],
    load_agents_from_mentors_fn: Callable[
        [ChangeSpec, str | None, str | None], list[Agent]
    ],
    load_agents_from_comments_fn: Callable[
        [ChangeSpec, str | None, str | None], list[Agent]
    ],
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources and return (agents, workflow_agent_steps)."""

    agents: list[Agent] = []
    project_files = get_all_project_files_fn()
    all_changespecs = (
        changespec_snapshot
        if changespec_snapshot is not None
        else find_all_changespecs_fn()
    )

    bug_by_cl_name: dict[str, str | None] = {}
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"
        if cs.cl:
            cl_by_cl_name[cs.name] = cs.cl

    agents.extend(
        load_agents_from_running_field_fn(
            project_files,
            bug_by_cl_name,
            cl_by_cl_name,
        )
    )

    if artifact_snapshot is None:
        artifact_snapshot = scan_artifacts_for_loader_fn()

    agents.extend(
        load_done_agents_from_snapshot_fn(
            artifact_snapshot,
            bug_by_cl_name,
            cl_by_cl_name,
        )
    )
    agents.extend(load_running_home_agents_from_snapshot_fn(artifact_snapshot))

    workflow_agent_steps, step_meta_by_parent = (
        load_workflow_agent_steps_from_snapshot_fn(artifact_snapshot)
    )

    agents.extend(
        load_workflow_agents_from_snapshot_fn(
            artifact_snapshot,
            step_meta_by_parent=step_meta_by_parent,
        )
    )

    for cs in all_changespecs:
        stripped_bug_id = cs.bug.removeprefix("http://b/") if cs.bug else None
        bug = f"http://b/{stripped_bug_id}" if stripped_bug_id else None
        cl_num = cs.cl

        agents.extend(load_agents_from_hooks_fn(cs, bug, cl_num))
        agents.extend(load_agents_from_mentors_fn(cs, bug, cl_num))
        agents.extend(load_agents_from_comments_fn(cs, bug, cl_num))

    return agents, workflow_agent_steps
