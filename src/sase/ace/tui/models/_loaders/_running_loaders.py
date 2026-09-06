"""Loaders for active agents (RUNNING field claims and home ``running.json``).

Discovers project spec files (canonical ``.sase`` with legacy ``.gp``
fallback), builds Agent records from active workspace claims, and
surfaces home-mode ace agents from filesystem markers or
:class:`AgentArtifactScanWire` snapshots.

Project lifecycle filtering is intentionally not applied here. ``RUNNING``
claims from disabled projects remain live work and must stay visible until
they finish or are cleaned up.

The ProjectSpec ``RUNNING`` field and home ``running.json`` marker are
liveness claims, not display-status claims. Rows start as ``STARTING`` and
metadata enrichment promotes them to ``RUNNING`` once ``run_started_at`` is
recorded.

Not every live claim is an agent: hook processes and machine-owned
operational leases (``lease(<workflow>)`` labels) hold workspaces without
being agent runs, so they are excluded before a row is built. Dead claims of
either kind are still reaped by the stale-release path first -- except a
pending gate shell's claim, which carries its killed creator's PID by design
and is held until the shell settles.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_scan_wire import (
    AgentArtifactRecordShape,
    AgentArtifactRecordWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    WaitingMarkerWire,
)
from sase.core.paths import sase_projects_dir
from sase.running_field import (
    WorkspaceClaim,
    get_claimed_workspaces,
    is_operational_lease_claim_workflow,
    release_workspace,
)

from ....agent_tribes import REVIEW_AGENT_TRIBE
from ....hooks.processes import is_process_running
from ._json_cache import load_json_cached
from ._meta_enrichment import (
    enrich_agent_from_prompt_markers,
    enrich_agent_from_prompt_markers_wire,
    enrich_agent_from_meta,
    enrich_agent_from_meta_wire,
)
from .._timestamps import (
    normalize_to_14_digit,
    parse_timestamp_14_digit,
    parse_timestamp_from_workflow_name,
)
from ..agent import Agent, AgentType

RunningAgentOrigin = Literal["local", "remote"]


@dataclass(frozen=True)
class RunningAgentContentHandle:
    """Opaque content handle carried by resolved running-agent rows."""

    origin: RunningAgentOrigin
    opaque_id: str
    local_artifact_dir: str | None = None
    record_shape: AgentArtifactRecordShape = "full"

    def __post_init__(self) -> None:
        if self.origin == "remote" and self.local_artifact_dir is not None:
            raise ValueError("remote running-agent handles must not expose local paths")


@dataclass(frozen=True)
class ResolvedRunningFieldClaim:
    """Owner-resolved project RUNNING claim ready for presentation."""

    project_file: str
    workspace_num: int
    workflow: str | None
    cl_name: str
    pid: int | None
    normalized_timestamp: str | None
    start_time: datetime | None
    agent_type: AgentType
    review_agent_workflow: bool = False


@dataclass(frozen=True)
class ResolvedRunningHomeAgentRecord:
    """Owner-resolved home running marker ready for pure row construction."""

    origin: RunningAgentOrigin
    content_handle: RunningAgentContentHandle
    project_file: str
    timestamp: str
    cl_name: str
    pid: int | None = None
    runner_is_live: bool = True
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None
    agent_meta: AgentMetaWire | None = None
    waiting: WaitingMarkerWire | None = None
    pending_question: PendingQuestionMarkerWire | None = None
    plan_path: PlanPathMarkerWire | None = None
    prompt_steps: tuple[PromptStepMarkerWire, ...] = ()

    def __post_init__(self) -> None:
        if self.origin != self.content_handle.origin:
            raise ValueError("running-agent record origin must match its handle")
        if self.origin == "remote":
            if self.pid is not None:
                raise ValueError("remote running-agent records must not expose PIDs")
            if self.workspace_dir is not None:
                raise ValueError(
                    "remote running-agent records must not expose local workspaces"
                )


def _is_review_agent_workflow_claim(workflow: str | None) -> bool:
    if not workflow:
        return False
    normalized = workflow.replace("-", "_")
    return any(
        normalized.startswith(prefix)
        for prefix in (
            "axe(mentor)",
            "axe(fix_hook)",
            "axe(summarize_hook)",
            "axe(crs)",
            "mentor(",
        )
    )


def _release_stale_running_claim(project_file: str, claim: WorkspaceClaim) -> None:
    """Best-effort release for a dead RUNNING-field claim."""
    if bool(getattr(claim, "pinned", False)):
        return
    try:
        release_workspace(
            project_file,
            claim.workspace_num,
            claim.workflow,
            claim.cl_name,
            caller_tag="ace-agents-loader",
        )
    except Exception:
        pass


def _stale_claim_is_releasable(project_file: str, claim: WorkspaceClaim) -> bool:
    """Return whether a dead-PID claim's workspace is genuinely free.

    A pending gate shell keeps its killed creator's PID in the RUNNING row
    on purpose, so for that one workflow a dead PID proves nothing and the
    gate shell's own markers decide. Imported lazily: this is only reached
    for a claim that already failed the liveness check.
    """
    from sase.gate_shell.claims import (
        GATE_WORKSPACE_CLAIM_WORKFLOW,
        gate_claim_is_releasable,
    )

    if claim.workflow != GATE_WORKSPACE_CLAIM_WORKFLOW:
        return True
    return gate_claim_is_releasable(project_file, claim)


def _claim_pid_is_live(pid: int | None) -> bool:
    return pid is not None and is_process_running(pid)


def _release_stale_running_home_marker(artifact_dir: Path) -> None:
    """Best-effort cleanup for a dead local home-mode ``running.json`` marker."""
    running_file = artifact_dir / "running.json"
    try:
        running_file.unlink(missing_ok=True)
        update_agent_artifact_index_for_marker_mutation(artifact_dir)
    except OSError:
        pass


def get_all_project_files() -> list[str]:
    """Get all project file paths across every lifecycle state.

    Returns:
        List of paths to project spec files. Prefers the canonical ``.sase``
        file per project and falls back to the legacy ``.gp`` file when the
        canonical sibling is not yet on disk.
    """
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    projects_dir = sase_projects_dir()

    if not projects_dir.exists():
        return []

    project_files: list[str] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        spec_path = preferred_project_spec_path(str(project_dir), project_name)
        if Path(spec_path).exists():
            project_files.append(spec_path)

    return project_files


def load_agents_from_running_field(
    project_files: list[str],
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Load agents from RUNNING field in all project files.

    Args:
        project_files: List of project file paths.
        bug_by_cl_name: Mapping of Patch names to bug URLs.
        cl_by_cl_name: Mapping of Patch names to PR numbers.

    Returns:
        List of Agent objects from RUNNING field claims.
    """
    return load_agents_from_resolved_running_claims(
        resolve_running_field_claims(project_files),
        bug_by_cl_name,
        cl_by_cl_name,
    )


def resolve_running_field_claims(
    project_files: list[str],
) -> list[ResolvedRunningFieldClaim]:
    """Resolve local RUNNING claims, including owner-side stale cleanup."""
    records: list[ResolvedRunningFieldClaim] = []
    for project_file in project_files:
        claims = get_claimed_workspaces(project_file)
        for claim in claims:
            if not _claim_pid_is_live(claim.pid):
                if _stale_claim_is_releasable(project_file, claim):
                    _release_stale_running_claim(project_file, claim)
                # A held pending gate-shell claim still contributes no row:
                # the gate-shell member renders from its own artifact record.
                continue

            # Skip hook processes - they're not agents
            # Hook processes have workflow like "axe(hooks)-1" or "axe(hooks)-1a"
            if claim.workflow and claim.workflow.startswith("axe(hooks)"):
                continue

            # Skip machine-owned operational leases (chops, bead-claim
            # reconciliation, plan archiving). They hold a pool workspace but
            # are not agents, and their cl_name is a lease holder identity
            # rather than an agent or Patch name.
            if is_operational_lease_claim_workflow(claim.workflow):
                continue

            # Detect workflow claims: workflow field starts with "workflow("
            is_workflow_claim = (
                claim.workflow
                and claim.workflow.startswith("workflow(")
                and claim.workflow.endswith(")")
            )

            if is_workflow_claim:
                # Extract workflow name from "workflow(name)"
                workflow_name = claim.workflow[9:-1]
                agent_type = AgentType.WORKFLOW
            else:
                workflow_name = claim.workflow
                agent_type = AgentType.RUNNING

            # Normalize timestamp (handles both 13-char and 14-digit formats)
            normalized_ts = normalize_to_14_digit(claim.artifacts_timestamp)
            start_time = (
                parse_timestamp_14_digit(normalized_ts)
                if normalized_ts
                else parse_timestamp_from_workflow_name(claim.workflow)
            )

            cl_name = claim.cl_name or "unknown"
            records.append(
                ResolvedRunningFieldClaim(
                    project_file=project_file,
                    workspace_num=claim.workspace_num,
                    workflow=workflow_name,
                    cl_name=cl_name,
                    pid=claim.pid,
                    normalized_timestamp=normalized_ts,
                    start_time=start_time,
                    agent_type=agent_type,
                    review_agent_workflow=_is_review_agent_workflow_claim(
                        claim.workflow
                    ),
                )
            )

    return records


def load_agents_from_resolved_running_claims(
    records: Iterable[ResolvedRunningFieldClaim],
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[Agent]:
    """Build Agent rows from already-resolved local RUNNING claims."""
    agents: list[Agent] = []
    for record in records:
        agent = Agent(
            agent_type=record.agent_type,
            cl_name=record.cl_name,
            project_file=record.project_file,
            status="STARTING",
            start_time=record.start_time,
            workspace_num=record.workspace_num,
            workflow=record.workflow,
            pid=record.pid,
            runner_is_live=True,
            raw_suffix=record.normalized_timestamp,
            bug=bug_by_cl_name.get(record.cl_name),
            cl_num=cl_by_cl_name.get(record.cl_name),
        )
        enrich_agent_from_meta(agent, agent.get_artifacts_dir())
        if record.review_agent_workflow:
            agent.tribe = REVIEW_AGENT_TRIBE
        agents.append(agent)
    return agents


def _local_running_home_handle(
    record: AgentArtifactRecordWire,
) -> RunningAgentContentHandle:
    return RunningAgentContentHandle(
        origin="local",
        opaque_id=record.artifact_dir,
        local_artifact_dir=record.artifact_dir,
        record_shape=record.record_shape,
    )


def _resolved_home_record_from_wire(
    record: AgentArtifactRecordWire,
    *,
    project_file: str,
    origin: RunningAgentOrigin,
    content_handle: RunningAgentContentHandle,
    runner_is_live: bool = True,
) -> ResolvedRunningHomeAgentRecord:
    running = record.running
    if running is None:
        raise ValueError("running home record requires a running marker")
    return ResolvedRunningHomeAgentRecord(
        origin=origin,
        content_handle=content_handle,
        project_file=project_file,
        timestamp=record.timestamp,
        cl_name=running.cl_name or "~",
        pid=running.pid if origin == "local" else None,
        runner_is_live=runner_is_live,
        model=running.model,
        llm_provider=running.llm_provider,
        vcs_provider=running.vcs_provider,
        workspace_dir=running.workspace_dir if origin == "local" else None,
        agent_meta=record.agent_meta,
        waiting=record.waiting,
        pending_question=record.pending_question,
        plan_path=record.plan_path,
        prompt_steps=tuple(record.prompt_steps),
    )


def resolve_running_home_records_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> list[ResolvedRunningHomeAgentRecord]:
    """Resolve local home-mode running records and clean up stale markers."""
    from sase.ace.patch.project_spec_path import preferred_project_spec_path

    records: list[ResolvedRunningHomeAgentRecord] = []
    home_project_file = preferred_project_spec_path(
        str(sase_projects_dir() / "home"), "home"
    )
    for record in snapshot.records:
        if record.project_name != "home":
            continue
        if record.workflow_dir_name != "ace-run":
            continue
        running = record.running
        if running is None:
            continue
        if not _claim_pid_is_live(running.pid):
            _release_stale_running_home_marker(Path(record.artifact_dir))
            continue

        records.append(
            _resolved_home_record_from_wire(
                record,
                project_file=home_project_file,
                origin="local",
                content_handle=_local_running_home_handle(record),
            )
        )

    return records


def load_running_home_agents_from_resolved_records(
    records: Iterable[ResolvedRunningHomeAgentRecord],
) -> list[Agent]:
    """Build Agent rows from owner-resolved home running records."""
    agents: list[Agent] = []
    for record in records:
        if not record.runner_is_live:
            continue
        local_artifact_dir = record.content_handle.local_artifact_dir
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=record.cl_name,
            project_file=record.project_file,
            status="STARTING",
            start_time=parse_timestamp_14_digit(record.timestamp),
            workflow="ace(run)",
            pid=record.pid,
            runner_is_live=record.runner_is_live,
            raw_suffix=record.timestamp,
            model=record.model,
            llm_provider=record.llm_provider,
            vcs_provider=record.vcs_provider,
            workspace_dir=record.workspace_dir,
            record_shape=record.content_handle.record_shape,
            index_record_dir=local_artifact_dir,
        )
        enrich_agent_from_meta_wire(
            agent,
            record.agent_meta,
            record.waiting,
            record.pending_question,
            plan_path_marker=(
                record.plan_path.plan_path if record.plan_path is not None else None
            ),
        )
        enrich_agent_from_prompt_markers_wire(agent, list(record.prompt_steps))
        agents.append(agent)
    return agents


def load_running_home_agents_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> list[Agent]:
    """Snapshot-aware mirror of :func:`load_running_home_agents`.

    Same selection filter (project ``home``, workflow ``ace-run``) and
    same liveness gate (``is_process_running``) as the filesystem helper.
    Stale ``running.json`` markers are still cleaned up best-effort to
    keep behavior parity, but the cleanup uses the absolute artifact
    path embedded in the record rather than rebuilding it.
    """
    return load_running_home_agents_from_resolved_records(
        resolve_running_home_records_from_snapshot(snapshot)
    )


def load_running_home_agents() -> list[Agent]:
    """Load running home mode agents from running.json marker files.

    Scans ~/.sase/projects/home/artifacts/ace-run/*/running.json for running agents.
    Only includes agents with PIDs that are still running.

    Returns:
        List of Agent objects with status="RUNNING".
    """
    agents: list[Agent] = []
    projects_dir = sase_projects_dir()
    home_project_dir = projects_dir / "home"
    if not home_project_dir.exists():
        return agents

    for artifact_dir in iter_agent_artifact_dirs(
        "home",
        "ace-run",
        projects_root=projects_dir,
    ):
        running_file = artifact_dir / "running.json"
        if not running_file.exists():
            continue

        try:
            data = load_json_cached(running_file)

            # Verify PID is still running
            pid = data.get("pid")
            if not _claim_pid_is_live(pid):
                # Process died - clean up the stale marker
                _release_stale_running_home_marker(artifact_dir)
                continue

            # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
            timestamp_str = artifact_dir.name
            start_time = parse_timestamp_14_digit(timestamp_str)

            cl_name = data.get("cl_name", "~")
            from sase.ace.patch.project_spec_path import (
                preferred_project_spec_path,
            )

            home_project_file = preferred_project_spec_path(
                str(sase_projects_dir() / "home"), "home"
            )
            agent = Agent(
                agent_type=AgentType.RUNNING,
                cl_name=cl_name,
                project_file=home_project_file,
                status="STARTING",
                start_time=start_time,
                workflow="ace(run)",
                pid=pid,
                runner_is_live=True,
                raw_suffix=timestamp_str,
                model=data.get("model"),
                llm_provider=data.get("llm_provider"),
                vcs_provider=data.get("vcs_provider"),
                workspace_dir=data.get("workspace_dir"),
            )
            enrich_agent_from_meta(agent, str(artifact_dir))
            enrich_agent_from_prompt_markers(agent, str(artifact_dir))
            agents.append(agent)
        except Exception:
            continue

    return agents
