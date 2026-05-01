"""Functions for loading and aggregating agents from all sources."""

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.agent_compose_wire import (
    AgentComposeInputWire,
    AgentComposeOptionsWire,
)
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.wire_conversion import changespec_to_wire

from ...changespec import ChangeSpec, find_all_changespecs
from ...hooks.processes import is_process_running
from ._dedup import (
    dedup_axe_spawned_agents,
    dedup_by_pid,
    dedup_running_vs_workflow,
    dedup_workflow_entries,
    remove_vcs_workspace_claims,
)
from ._loaders import (
    collect_running_claim_wires,
    get_all_project_files,
    get_workflow_timestamp_dirs,  # noqa: F401  re-exported for fallback callers
    load_agents_from_comments,
    load_agents_from_hooks,
    load_agents_from_mentors,
    load_agents_from_running_field,
    load_done_agents,  # noqa: F401  re-exported for fallback/tests
    load_done_agents_from_snapshot,
    load_running_home_agents,  # noqa: F401  re-exported for fallback/tests
    load_running_home_agents_from_snapshot,
    load_workflow_agent_steps,  # noqa: F401  re-exported for fallback/tests
    load_workflow_agent_steps_from_snapshot,
    load_workflow_agents,  # noqa: F401  re-exported for fallback/tests
    load_workflow_agents_from_snapshot,
    load_workflow_states,  # noqa: F401  re-exported for fallback/tests
    load_workflow_states_from_snapshot,  # noqa: F401  re-exported for fallback/tests
)
from .agent import Agent, AgentType
from .agent_loader_backend import (
    agent_compose_backend,
    compose_rust_agent_list_with_dismissed,
    dismissed_from_agents,
    shadow_compare_agent_compose,
)
from .agent_loader_ordering import sort_and_reorder
from .agent_loader_status import (
    apply_status_overrides,
)
from .workflow import WorkflowEntry

if TYPE_CHECKING:
    from sase.core.agent_compose_wire import RunningClaimWire


_TUI_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    # The TUI reads prompt-step markers (workflow agent steps + meta_*
    # propagation) but does not render the raw_xprompt.md snippet; skip
    # the snippet read to keep the scan compact.
    include_raw_prompt_snippets=False,
)


@dataclass(frozen=True)
class _AgentLoaderCompositionInputs:
    project_files: list[str]
    changespecs: list[ChangeSpec]
    bug_by_cl_name: dict[str, str | None]
    cl_by_cl_name: dict[str, str | None]
    artifact_snapshot: AgentArtifactScanWire
    running_claims: list["RunningClaimWire"]
    compose_input: AgentComposeInputWire


def _apply_status_overrides(agents: list[Agent]) -> None:
    """Compatibility wrapper for tests/benchmarks importing from agent_loader."""
    apply_status_overrides(agents)


def _sort_and_reorder(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
) -> list[Agent]:
    """Compatibility wrapper for tests/benchmarks importing from agent_loader."""
    return sort_and_reorder(agents, workflow_agent_steps)


def _agent_compose_backend() -> str:
    return agent_compose_backend()


def _dismissed_from_agents(
    agents: list[Agent],
    dismissed_agents: set[tuple[AgentType, str, str | None]] | None,
) -> list[Agent]:
    return dismissed_from_agents(agents, dismissed_agents)


def _shadow_compare_agent_compose(
    compose_input: AgentComposeInputWire,
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    dismissed_from_loader: list[Agent],
) -> None:
    shadow_compare_agent_compose(
        compose_input,
        agents,
        workflow_agent_steps,
        dismissed_from_loader,
    )


def _compose_rust_agent_list_with_dismissed(
    compose_input: AgentComposeInputWire,
) -> tuple[list[Agent], list[Agent]]:
    return compose_rust_agent_list_with_dismissed(compose_input)


def _scan_artifacts_for_loader() -> "AgentArtifactScanWire":
    """Return one fresh artifact-tree snapshot for the TUI loader.

    Single-purpose seam between :func:`_load_agents_from_all_sources` and
    :func:`scan_agent_artifacts` so tests can replace the snapshot with a
    fixture without having to patch every individual ``_from_snapshot``
    consumer.
    """
    return scan_agent_artifacts(
        Path("~/.sase/projects").expanduser(),
        _TUI_SCAN_OPTIONS,
    )


def load_all_workflows() -> list[WorkflowEntry]:
    """Load all workflow entries from workflow_state.json files.

    Returns:
        List of WorkflowEntry objects sorted by start time (most recent first).
    """
    workflows = load_workflow_states()

    # Sort by start time (most recent first)
    workflows_with_time = [w for w in workflows if w.start_time is not None]
    workflows_without_time = [w for w in workflows if w.start_time is None]

    workflows_with_time.sort(key=lambda w: w.start_time, reverse=True)  # type: ignore

    return workflows_with_time + workflows_without_time


def _identity_to_wire(
    identity: tuple[AgentType, str, str | None],
) -> tuple[str, str, str | None]:
    agent_type, cl_name, raw_suffix = identity
    return (agent_type.value, cl_name, raw_suffix)


def _build_changespec_lookups(
    all_changespecs: list[ChangeSpec],
) -> tuple[dict[str, str | None], dict[str, str | None]]:
    """Build bug URL and CL number lookups by CL name."""
    bug_by_cl_name: dict[str, str | None] = {}
    cl_by_cl_name: dict[str, str | None] = {}
    for cs in all_changespecs:
        if cs.bug:
            bug_id = cs.bug.removeprefix("http://b/")
            bug_by_cl_name[cs.name] = f"http://b/{bug_id}"
        if cs.cl:
            cl_by_cl_name[cs.name] = cs.cl
    return bug_by_cl_name, cl_by_cl_name


def _collect_agent_loader_inputs(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    dismissed_agents: set[tuple[AgentType, str, str | None]] | None = None,
) -> _AgentLoaderCompositionInputs:
    """Collect every coarse-grained input needed for one compose pass."""
    project_files = get_all_project_files()
    all_changespecs = (
        changespec_snapshot
        if changespec_snapshot is not None
        else find_all_changespecs()
    )
    bug_by_cl_name, cl_by_cl_name = _build_changespec_lookups(all_changespecs)
    running_claims = collect_running_claim_wires(
        project_files, bug_by_cl_name, cl_by_cl_name
    )
    artifact_snapshot = _scan_artifacts_for_loader()
    dismissed = dismissed_agents or set()
    compose_input = AgentComposeInputWire(
        artifact_scan=artifact_snapshot,
        changespecs=[changespec_to_wire(cs) for cs in all_changespecs],
        running_claims=running_claims,
        dismissed_identities=[_identity_to_wire(identity) for identity in dismissed],
        dismissed_suffixes=[
            raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None
        ],
        options=AgentComposeOptionsWire(),
    )
    return _AgentLoaderCompositionInputs(
        project_files=project_files,
        changespecs=all_changespecs,
        bug_by_cl_name=bug_by_cl_name,
        cl_by_cl_name=cl_by_cl_name,
        artifact_snapshot=artifact_snapshot,
        running_claims=running_claims,
        compose_input=compose_input,
    )


def _load_agents_from_all_sources(
    *, changespec_snapshot: list[ChangeSpec] | None = None
) -> tuple[list[Agent], list[Agent]]:
    """Load agents from all sources and return (agents, workflow_agent_steps).

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. done.json marker files (DONE agents)
    3. running.json markers (home mode agents)
    4. Workflow agent steps and workflow entries
    5. HOOKS, MENTORS, COMMENTS fields from ChangeSpecs

    Args:
        changespec_snapshot: Optional pre-fetched ChangeSpec list. When
            supplied, the loader skips the in-process ``find_all_changespecs()``
            call and reuses this snapshot for bug/CL lookups and the
            HOOKS/MENTORS/COMMENTS sweep.
    """
    inputs = _collect_agent_loader_inputs(changespec_snapshot=changespec_snapshot)
    return _load_agents_from_collected_sources(inputs)


def _load_agents_from_collected_sources(
    inputs: _AgentLoaderCompositionInputs,
) -> tuple[list[Agent], list[Agent]]:
    """Build Python Agent candidates from already-collected loader inputs."""
    agents: list[Agent] = []

    # 1. Load from RUNNING field (snapshot-independent; reads project .gp files).
    agents.extend(
        load_agents_from_running_field(
            inputs.project_files,
            inputs.bug_by_cl_name,
            inputs.cl_by_cl_name,
            running_claims=inputs.running_claims,
        )
    )

    # 1a. Load completed (DONE) agents
    agents.extend(
        load_done_agents_from_snapshot(
            inputs.artifact_snapshot,
            inputs.bug_by_cl_name,
            inputs.cl_by_cl_name,
        )
    )

    # 1b. Load running home mode agents (from running.json markers)
    agents.extend(load_running_home_agents_from_snapshot(inputs.artifact_snapshot))

    # 1d. Load workflow agent steps first — also collects meta_* fields
    # per parent timestamp so load_workflow_agents() can skip redundant
    # prompt_step_*.json reads.
    workflow_agent_steps, step_meta_by_parent = load_workflow_agent_steps_from_snapshot(
        inputs.artifact_snapshot
    )

    # 1c. Load workflow entries as agents (with pre-collected meta fields)
    agents.extend(
        load_workflow_agents_from_snapshot(
            inputs.artifact_snapshot,
            step_meta_by_parent=step_meta_by_parent,
        )
    )

    # 2. Load from each ChangeSpec's fields
    for cs in inputs.changespecs:
        stripped_bug_id = cs.bug.removeprefix("http://b/") if cs.bug else None
        bug = f"http://b/{stripped_bug_id}" if stripped_bug_id else None
        cl_num = cs.cl

        # HOOKS - fix-hook and summarize agents
        agents.extend(load_agents_from_hooks(cs, bug, cl_num))

        # MENTORS - mentor agents
        agents.extend(load_agents_from_mentors(cs, bug, cl_num))

        # COMMENTS - CRS agents
        agents.extend(load_agents_from_comments(cs, bug, cl_num))

    return agents, workflow_agent_steps


def _artifact_running_pids(snapshot: AgentArtifactScanWire) -> set[int]:
    pids: set[int] = set()
    for record in snapshot.records:
        if record.running is not None and record.running.pid is not None:
            pids.add(record.running.pid)
    return pids


def _collect_pid_liveness(
    agents: list[Agent],
    *,
    artifact_snapshot: AgentArtifactScanWire | None = None,
) -> dict[int, bool]:
    """Check each PID once for Python filtering and Rust shadow input."""
    pids = {agent.pid for agent in agents if agent.pid is not None}
    if artifact_snapshot is not None:
        pids.update(_artifact_running_pids(artifact_snapshot))
    return {pid: is_process_running(pid) for pid in sorted(pids)}


def _compose_input_with_liveness(
    compose_input: AgentComposeInputWire,
    pid_liveness: dict[int, bool],
) -> AgentComposeInputWire:
    return replace(
        compose_input,
        alive_pids=[pid for pid, alive in pid_liveness.items() if alive],
        dead_pids=[pid for pid, alive in pid_liveness.items() if not alive],
    )


def _filter_dead_pids(
    agents: list[Agent],
    *,
    pid_liveness: dict[int, bool] | None = None,
) -> list[Agent]:
    """Filter out agents with dead PIDs (but keep completed agents)."""
    verified_agents: list[Agent] = []
    completed_statuses = ("DONE", "FAILED")
    for agent in agents:
        if agent.status in completed_statuses:
            verified_agents.append(agent)
        elif agent.pid is not None:
            is_alive = (
                pid_liveness[agent.pid]
                if pid_liveness is not None and agent.pid in pid_liveness
                else is_process_running(agent.pid)
            )
            if is_alive:
                verified_agents.append(agent)
            # Skip agents with dead PIDs
        else:
            # Agents without PIDs (legacy entries) - still include them
            verified_agents.append(agent)
    return verified_agents


def _compose_python_agent_list(
    agents: list[Agent],
    workflow_agent_steps: list[Agent],
    *,
    pid_liveness: dict[int, bool] | None = None,
) -> list[Agent]:
    """Run the current Python composition stages on preloaded candidates."""
    # Filter out agents with dead PIDs (but keep completed agents)
    agents = _filter_dead_pids(agents, pid_liveness=pid_liveness)

    # Deduplication pipeline
    agents = dedup_axe_spawned_agents(agents)
    agents = remove_vcs_workspace_claims(agents)
    agents = dedup_workflow_entries(agents)
    agents = dedup_running_vs_workflow(agents)
    agents = dedup_by_pid(agents)

    # Override statuses based on workflow relationships
    _apply_status_overrides(agents)

    # Sort and insert workflow steps
    return _sort_and_reorder(agents, workflow_agent_steps)


def load_all_agents_with_dismissed(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    dismissed_agents: set[tuple[AgentType, str, str | None]] | None = None,
) -> tuple[list[Agent], list[Agent]]:
    """Load all running agents and loader-sourced dismissed agents.

    Sources:
    1. RUNNING field in project files (workspace claims)
    2. HOOKS field with suffix_type="running_agent" (fix_hook, summarize_hook)
    3. MENTORS field with suffix_type="running_agent"
    4. COMMENTS field with suffix_type="running_agent" (CRS)
    5. done.json marker files (DONE agents)

    Args:
        changespec_snapshot: Optional pre-fetched ChangeSpec list. When
            supplied, the loader skips its own ``find_all_changespecs()``
            call and reuses this snapshot.

    Returns:
        Tuple of (visible agents, dismissed agents found by the loader).
    """
    backend = _agent_compose_backend()
    inputs = _collect_agent_loader_inputs(
        changespec_snapshot=changespec_snapshot,
        dismissed_agents=dismissed_agents,
    )
    agents, workflow_agent_steps = _load_agents_from_collected_sources(inputs)
    pid_liveness = _collect_pid_liveness(
        agents, artifact_snapshot=inputs.artifact_snapshot
    )
    compose_input = _compose_input_with_liveness(inputs.compose_input, pid_liveness)

    if backend == "rust":
        return _compose_rust_agent_list_with_dismissed(compose_input)

    composed_agents = _compose_python_agent_list(
        agents,
        workflow_agent_steps,
        pid_liveness=pid_liveness,
    )
    dismissed_from_loader = _dismissed_from_agents(composed_agents, dismissed_agents)
    _shadow_compare_agent_compose(
        compose_input,
        composed_agents,
        workflow_agent_steps,
        dismissed_from_loader,
    )
    return composed_agents, dismissed_from_loader


def load_all_agents(
    *,
    changespec_snapshot: list[ChangeSpec] | None = None,
    dismissed_agents: set[tuple[AgentType, str, str | None]] | None = None,
) -> list[Agent]:
    """Load visible running agents from all sources."""
    agents, _ = load_all_agents_with_dismissed(
        changespec_snapshot=changespec_snapshot,
        dismissed_agents=dismissed_agents,
    )
    return agents
