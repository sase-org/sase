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

from ...changespec import (
    ChangeSpec,
    extract_pid_from_agent_suffix,
    find_all_changespecs,
)
from ...hooks.processes import is_process_running
from ._loaders import (
    collect_running_claim_wires,
    get_all_project_files,
    load_workflow_states,  # noqa: F401  re-exported for fallback/tests
    load_workflow_states_from_snapshot,  # noqa: F401  re-exported for fallback/tests
)
from .agent import Agent, AgentType
from .agent_loader_backend import (
    compose_rust_agent_list_with_dismissed,
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


def _compose_rust_agent_list_with_dismissed(
    compose_input: AgentComposeInputWire,
) -> tuple[list[Agent], list[Agent]]:
    return compose_rust_agent_list_with_dismissed(compose_input)


def _scan_artifacts_for_loader() -> "AgentArtifactScanWire":
    """Return one fresh artifact-tree snapshot for the TUI loader.

    Single-purpose seam between the TUI loader input collection and
    :func:`scan_agent_artifacts` so tests can replace the snapshot with a
    fixture.
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


def _artifact_running_pids(snapshot: AgentArtifactScanWire) -> set[int]:
    pids: set[int] = set()
    for record in snapshot.records:
        if record.running is not None and record.running.pid is not None:
            pids.add(record.running.pid)
    return pids


def _artifact_workflow_state_pids(snapshot: AgentArtifactScanWire) -> set[int]:
    pids: set[int] = set()
    for record in snapshot.records:
        state = record.workflow_state
        if state is not None and state.pid is not None:
            pids.add(state.pid)
    return pids


def _changespec_running_agent_pids(compose_input: AgentComposeInputWire) -> set[int]:
    pids: set[int] = set()
    for changespec in compose_input.changespecs:
        for hook in changespec.hooks:
            for status_line in hook.status_lines:
                if status_line.suffix_type == "running_agent":
                    pid = extract_pid_from_agent_suffix(status_line.suffix)
                    if pid is not None:
                        pids.add(pid)
        for mentor in changespec.mentors:
            for mentor_status_line in mentor.status_lines:
                if mentor_status_line.suffix_type == "running_agent":
                    pid = extract_pid_from_agent_suffix(mentor_status_line.suffix)
                    if pid is not None:
                        pids.add(pid)
        for comment in changespec.comments:
            if comment.suffix_type == "running_agent":
                pid = extract_pid_from_agent_suffix(comment.suffix)
                if pid is not None:
                    pids.add(pid)
    return pids


def _collect_compose_input_pids(compose_input: AgentComposeInputWire) -> set[int]:
    """Collect all process IDs whose liveness the host must verify."""
    pids = {
        claim.pid for claim in compose_input.running_claims if claim.pid is not None
    }
    if compose_input.artifact_scan is not None:
        pids.update(_artifact_running_pids(compose_input.artifact_scan))
        pids.update(_artifact_workflow_state_pids(compose_input.artifact_scan))
    pids.update(_changespec_running_agent_pids(compose_input))
    return pids


def _collect_pid_liveness_from_compose_input(
    compose_input: AgentComposeInputWire,
) -> dict[int, bool]:
    """Check each wire-input PID once before deterministic Rust composition."""
    pids = _collect_compose_input_pids(compose_input)
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
    inputs = _collect_agent_loader_inputs(
        changespec_snapshot=changespec_snapshot,
        dismissed_agents=dismissed_agents,
    )
    pid_liveness = _collect_pid_liveness_from_compose_input(inputs.compose_input)
    compose_input = _compose_input_with_liveness(inputs.compose_input, pid_liveness)
    return _compose_rust_agent_list_with_dismissed(compose_input)


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
