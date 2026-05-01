"""Loaders for running agents (RUNNING field claims and home-mode ``running.json``).

Discovers project ``.gp`` files, builds Agent records from active workspace
claims, and surfaces home-mode ace agents from filesystem markers or
:class:`AgentArtifactScanWire` snapshots.
"""

from pathlib import Path

from sase.running_field import get_claimed_workspaces
from sase.core.agent_compose_wire import RunningClaimWire
from sase.core.agent_scan_wire import AgentArtifactScanWire

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


def get_all_project_files() -> list[str]:
    """Get all project file paths.

    Returns:
        List of paths to .gp files.
    """
    projects_dir = Path.home() / ".sase" / "projects"

    if not projects_dir.exists():
        return []

    project_files: list[str] = []

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        project_name = project_dir.name
        gp_file = project_dir / f"{project_name}.gp"

        if gp_file.exists():
            project_files.append(str(gp_file))

    return project_files


def collect_running_claim_wires(
    project_files: list[str],
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
) -> list[RunningClaimWire]:
    """Collect RUNNING-field claims once in the compose wire shape."""
    claims: list[RunningClaimWire] = []
    for project_file in project_files:
        project_name = Path(project_file).parent.name
        for claim in get_claimed_workspaces(project_file):
            cl_name = claim.cl_name or "unknown"
            claims.append(
                RunningClaimWire(
                    project_file=project_file,
                    project_name=project_name,
                    cl_name=cl_name,
                    workspace_num=claim.workspace_num,
                    workflow=claim.workflow,
                    raw_suffix=claim.artifacts_timestamp,
                    pid=claim.pid,
                    bug=bug_by_cl_name.get(cl_name),
                    cl_num=cl_by_cl_name.get(cl_name),
                )
            )
    return claims


def _load_agents_from_running_claim_wires(
    running_claims: list[RunningClaimWire],
) -> list[Agent]:
    """Build Agent records from pre-collected RUNNING-field claim wires."""
    agents: list[Agent] = []

    for claim in running_claims:
        raw_workflow = claim.workflow
        # Skip hook processes - they're not agents
        # Hook processes have workflow like "axe(hooks)-1" or "axe(hooks)-1a"
        if raw_workflow and raw_workflow.startswith("axe(hooks)"):
            continue

        # Detect workflow claims: workflow field starts with "workflow("
        is_workflow_claim = (
            raw_workflow is not None
            and raw_workflow.startswith("workflow(")
            and raw_workflow.endswith(")")
        )

        workflow_name: str | None
        if is_workflow_claim and raw_workflow is not None:
            # Extract workflow name from "workflow(name)"
            workflow_name = raw_workflow[9:-1]
            agent_type = AgentType.WORKFLOW
        else:
            workflow_name = raw_workflow
            agent_type = AgentType.RUNNING

        # Normalize timestamp (handles both 13-char and 14-digit formats)
        normalized_ts = normalize_to_14_digit(claim.raw_suffix)
        start_time = (
            parse_timestamp_14_digit(normalized_ts)
            if normalized_ts
            else parse_timestamp_from_workflow_name(raw_workflow)
        )

        agent = Agent(
            agent_type=agent_type,
            cl_name=claim.cl_name or "unknown",
            project_file=claim.project_file,
            status="RUNNING",
            start_time=start_time,
            workspace_num=claim.workspace_num,
            workflow=workflow_name,
            pid=claim.pid,
            # Use normalized timestamp as raw_suffix for prompt lookup
            raw_suffix=normalized_ts,
            bug=claim.bug,
            cl_num=claim.cl_num,
            model=claim.model,
            llm_provider=claim.llm_provider,
            vcs_provider=claim.vcs_provider,
            workspace_dir=claim.workspace_dir,
            agent_name=claim.agent_name,
            approve=claim.approve,
            hidden=claim.hidden,
        )
        enrich_agent_from_meta(agent, agent.get_artifacts_dir())
        # Axe-spawned agents are always hidden
        # Normalize hyphens to underscores (canonical form uses underscores,
        # e.g. xprompt workflow_label "fix_hook")
        if raw_workflow and any(
            raw_workflow.replace("-", "_").startswith(p)
            for p in ["axe(mentor)", "axe(fix_hook)", "axe(crs)", "mentor("]
        ):
            agent.hidden = True
        agents.append(agent)

    return agents


def load_agents_from_running_field(
    project_files: list[str],
    bug_by_cl_name: dict[str, str | None],
    cl_by_cl_name: dict[str, str | None],
    *,
    running_claims: list[RunningClaimWire] | None = None,
) -> list[Agent]:
    """Load agents from RUNNING field in all project files.

    Args:
        project_files: List of project file paths.
        bug_by_cl_name: Mapping of CL names to bug URLs.
        cl_by_cl_name: Mapping of CL names to CL numbers.

    Returns:
        List of Agent objects from RUNNING field claims.
    """
    claims = running_claims
    if claims is None:
        claims = collect_running_claim_wires(
            project_files, bug_by_cl_name, cl_by_cl_name
        )
    return _load_agents_from_running_claim_wires(claims)


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
    agents: list[Agent] = []
    home_project_file = str(Path.home() / ".sase" / "projects" / "home" / "home.gp")
    for record in snapshot.records:
        if record.project_name != "home":
            continue
        if record.workflow_dir_name != "ace-run":
            continue
        running = record.running
        if running is None:
            continue
        pid = running.pid
        if pid is None or not is_process_running(pid):
            running_file = Path(record.artifact_dir) / "running.json"
            try:
                running_file.unlink()
            except OSError:
                pass
            continue

        start_time = parse_timestamp_14_digit(record.timestamp)
        cl_name = running.cl_name or "~"
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=cl_name,
            project_file=home_project_file,
            status="RUNNING",
            start_time=start_time,
            workflow="ace(run)",
            pid=pid,
            raw_suffix=record.timestamp,
            model=running.model,
            llm_provider=running.llm_provider,
            vcs_provider=running.vcs_provider,
            workspace_dir=running.workspace_dir,
        )
        enrich_agent_from_meta_wire(agent, record.agent_meta, record.waiting)
        enrich_agent_from_prompt_markers_wire(agent, record.prompt_steps)
        agents.append(agent)
    return agents


def load_running_home_agents() -> list[Agent]:
    """Load running home mode agents from running.json marker files.

    Scans ~/.sase/projects/home/artifacts/ace-run/*/running.json for running agents.
    Only includes agents with PIDs that are still running.

    Returns:
        List of Agent objects with status="RUNNING".
    """
    agents: list[Agent] = []
    home_ace_run_dir = (
        Path.home() / ".sase" / "projects" / "home" / "artifacts" / "ace-run"
    )

    if not home_ace_run_dir.exists():
        return agents

    for artifact_dir in home_ace_run_dir.iterdir():
        if not artifact_dir.is_dir():
            continue

        running_file = artifact_dir / "running.json"
        if not running_file.exists():
            continue

        try:
            data = load_json_cached(running_file)

            # Verify PID is still running
            pid = data.get("pid")
            if pid is None or not is_process_running(pid):
                # Process died - clean up the stale marker
                try:
                    running_file.unlink()
                except OSError:
                    pass
                continue

            # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
            timestamp_str = artifact_dir.name
            start_time = parse_timestamp_14_digit(timestamp_str)

            cl_name = data.get("cl_name", "~")
            agent = Agent(
                agent_type=AgentType.RUNNING,
                cl_name=cl_name,
                project_file=str(
                    Path.home() / ".sase" / "projects" / "home" / "home.gp"
                ),
                status="RUNNING",
                start_time=start_time,
                workflow="ace(run)",
                pid=pid,
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
