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
"""

from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.core.paths import sase_projects_dir
from sase.running_field import WorkspaceClaim, get_claimed_workspaces, release_workspace

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
        )
    except Exception:
        pass


def _claim_pid_is_live(pid: int | None) -> bool:
    return pid is not None and is_process_running(pid)


def get_all_project_files() -> list[str]:
    """Get all project file paths across every lifecycle state.

    Returns:
        List of paths to project spec files. Prefers the canonical ``.sase``
        file per project and falls back to the legacy ``.gp`` file when the
        canonical sibling is not yet on disk.
    """
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

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
        bug_by_cl_name: Mapping of ChangeSpec names to bug URLs.
        cl_by_cl_name: Mapping of ChangeSpec names to PR numbers.

    Returns:
        List of Agent objects from RUNNING field claims.
    """
    agents: list[Agent] = []

    for project_file in project_files:
        claims = get_claimed_workspaces(project_file)
        for claim in claims:
            if not _claim_pid_is_live(claim.pid):
                _release_stale_running_claim(project_file, claim)
                continue

            # Skip hook processes - they're not agents
            # Hook processes have workflow like "axe(hooks)-1" or "axe(hooks)-1a"
            if claim.workflow and claim.workflow.startswith("axe(hooks)"):
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
            agent = Agent(
                agent_type=agent_type,
                cl_name=cl_name,
                project_file=project_file,
                status="STARTING",
                start_time=start_time,
                workspace_num=claim.workspace_num,
                workflow=workflow_name,
                pid=claim.pid,
                runner_is_live=True,
                # Use normalized timestamp as raw_suffix for prompt lookup
                raw_suffix=normalized_ts,
                bug=bug_by_cl_name.get(cl_name),
                cl_num=cl_by_cl_name.get(cl_name),
            )
            enrich_agent_from_meta(agent, agent.get_artifacts_dir())
            if _is_review_agent_workflow_claim(claim.workflow):
                agent.tribe = REVIEW_AGENT_TRIBE
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
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    agents: list[Agent] = []
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
        pid = running.pid
        if pid is None or not is_process_running(pid):
            artifact_dir = Path(record.artifact_dir)
            running_file = Path(record.artifact_dir) / "running.json"
            try:
                running_file.unlink(missing_ok=True)
                update_agent_artifact_index_for_marker_mutation(artifact_dir)
            except OSError:
                pass
            continue

        start_time = parse_timestamp_14_digit(record.timestamp)
        cl_name = running.cl_name or "~"
        agent = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=cl_name,
            project_file=home_project_file,
            status="STARTING",
            start_time=start_time,
            workflow="ace(run)",
            pid=pid,
            runner_is_live=True,
            raw_suffix=record.timestamp,
            model=running.model,
            llm_provider=running.llm_provider,
            vcs_provider=running.vcs_provider,
            workspace_dir=running.workspace_dir,
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
            if pid is None or not is_process_running(pid):
                # Process died - clean up the stale marker
                try:
                    running_file.unlink(missing_ok=True)
                    update_agent_artifact_index_for_marker_mutation(artifact_dir)
                except OSError:
                    pass
                continue

            # Parse timestamp from artifact dir name (YYYYmmddHHMMSS)
            timestamp_str = artifact_dir.name
            start_time = parse_timestamp_14_digit(timestamp_str)

            cl_name = data.get("cl_name", "~")
            from sase.ace.changespec.project_spec_path import (
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
