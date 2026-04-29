"""Running agent listing and lifecycle management.

Provides functions to list currently running agents across all projects
and to kill agents by name.

Phase 3E (sase-18.5) routes the artifact walks through the
:func:`sase.core.agent_scan_facade.scan_agent_artifacts` snapshot so a
single scan amortizes across both ``list_running_agents`` and
``list_all_agents``. Process-liveness checks and ``.gp`` RUNNING-field
parsing remain in Python — only the artifact walk and JSON parsing move
behind the facade.
"""

import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.agent.names import find_named_agent, is_process_alive
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.time import get_timezone


@dataclass
class _KillResult:
    """Result of a kill_named_agent() attempt."""

    success: bool
    message: str


@dataclass
class RunningAgentInfo:
    """Summary info for a running agent.

    ``status`` defaults to ``"RUNNING"`` for entries produced by
    :func:`list_running_agents`; :func:`list_all_agents` may additionally
    emit ``"DONE"`` and ``"FAILED"``.
    """

    name: str | None
    project: str
    pid: int | None
    model: str | None
    provider: str | None
    workspace_num: int | None
    duration: str
    approve: bool
    prompt: str | None = None
    status: str = "RUNNING"
    started_at: datetime | None = None
    duration_seconds: int | None = None
    artifacts_dir: str | None = None


_DONE_AGENTS_CAP_PER_PROJECT = 50

# Only the running/done CLI listing needs ace-run records. Skipping prompt
# step markers avoids the per-directory glob the facade would otherwise do.
_LISTING_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    only_workflow_dirs=("ace-run",),
)


def _scan_listing_snapshot() -> AgentArtifactScanWire:
    """Acquire one ace-run snapshot for the CLI listing call sites."""
    # Local import: ``sase.core.agent_scan_facade`` pulls in the TUI loader
    # chain at import time (for the shared mtime cache), which transitively
    # imports ``sase.agent`` again. A module-level import here would
    # circle back through ``sase.agent.__init__`` and fail during startup.
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(
        Path.home() / ".sase" / "projects",
        _LISTING_SCAN_OPTIONS,
    )


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes}m"
    if minutes > 0:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def _parse_started_at(timestamp: str) -> datetime | None:
    try:
        return datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=get_timezone()
        )
    except ValueError:
        return None


def _resolve_workspace_num(
    *,
    project_name: str,
    project_file: str,
    timestamp: str,
    cache: dict[str, list],
) -> int | None:
    """Look up the workspace number for *timestamp* via the project's RUNNING field.

    ``.gp`` parsing stays Python-only in Phase 3; we cache the result per
    project file so a listing with N artifacts in one project still parses
    that project's claims at most once.
    """
    if project_name == "home":
        return None
    try:
        from sase.running_field import get_claimed_workspaces

        claims = cache.get(project_file)
        if claims is None:
            claims = list(get_claimed_workspaces(project_file))
            cache[project_file] = claims
        for claim in claims:
            if claim.artifacts_timestamp == timestamp:
                return claim.workspace_num
    except Exception:
        return None
    return None


def _running_info_from_running_record(
    record: AgentArtifactRecordWire,
    *,
    now: datetime,
    workspace_cache: dict[str, list],
) -> RunningAgentInfo | None:
    """Adapt a snapshot record into RunningAgentInfo, or skip via current filters."""
    meta = record.agent_meta
    if meta is None:
        return None
    if meta.parent_timestamp:
        return None
    wf_state = record.workflow_state
    if wf_state is not None and not wf_state.appears_as_agent:
        return None

    pid = meta.pid
    if pid is None and record.running is not None:
        pid = record.running.pid
    meta_dict: dict[str, object] = {"pid": pid, "stopped_at": meta.stopped_at}
    if not is_process_alive(meta_dict, Path(record.artifact_dir)):
        return None

    started_at = _parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if started_at is not None:
        duration_seconds = int((now - started_at).total_seconds())
        duration = _format_duration(duration_seconds)

    workspace_num = _resolve_workspace_num(
        project_name=record.project_name,
        project_file=record.project_file,
        timestamp=record.timestamp,
        cache=workspace_cache,
    )

    return RunningAgentInfo(
        name=meta.name,
        project=record.project_name,
        pid=meta.pid,
        model=meta.model,
        provider=meta.llm_provider,
        workspace_num=workspace_num,
        duration=duration,
        approve=bool(meta.approve),
        prompt=record.raw_prompt_snippet,
        status="RUNNING",
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=record.artifact_dir,
    )


def _running_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> list[RunningAgentInfo]:
    """Build the running-agent list from *snapshot* using current Python filters."""
    now = datetime.now(get_timezone())
    workspace_cache: dict[str, list] = {}
    pairs: list[tuple[str, RunningAgentInfo]] = []

    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        if record.has_done_marker:
            continue
        info = _running_info_from_running_record(
            record, now=now, workspace_cache=workspace_cache
        )
        if info is None:
            continue
        pairs.append((record.timestamp, info))

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


def _done_info_from_record(
    record: AgentArtifactRecordWire,
) -> RunningAgentInfo | None:
    """Adapt a done-marker snapshot record into RunningAgentInfo, or skip."""
    if not record.has_done_marker:
        return None
    done = record.done
    if done is None:
        return None

    meta = record.agent_meta

    if meta is not None and meta.parent_timestamp:
        return None

    wf_state = record.workflow_state
    if wf_state is not None and not wf_state.appears_as_agent:
        return None

    outcome = done.outcome or "completed"
    if outcome == "noop":
        return None
    status = "FAILED" if outcome == "failed" else "DONE"

    started_at = _parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if started_at is not None:
        if done.finished_at is not None:
            end = datetime.fromtimestamp(float(done.finished_at), get_timezone())
        else:
            end = datetime.now(get_timezone())
        duration_seconds = int((end - started_at).total_seconds())
        duration = _format_duration(duration_seconds)

    name = (meta.name if meta is not None else None) or done.name
    pid = (meta.pid if meta is not None else None) or done.pid
    model = (meta.model if meta is not None else None) or done.model
    provider = (meta.llm_provider if meta is not None else None) or done.llm_provider
    approve = bool((meta.approve if meta is not None else False) or done.approve)

    return RunningAgentInfo(
        name=name,
        project=record.project_name,
        pid=pid,
        model=model,
        provider=provider,
        workspace_num=done.workspace_num,
        duration=duration,
        approve=approve,
        prompt=record.raw_prompt_snippet,
        status=status,
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=record.artifact_dir,
    )


def _done_from_snapshot(
    snapshot: AgentArtifactScanWire,
    *,
    cap_per_project: int,
) -> list[RunningAgentInfo]:
    """Build the recently-completed list from *snapshot* with per-project cap."""
    by_project: dict[str, list[AgentArtifactRecordWire]] = {}
    for record in snapshot.records:
        if record.workflow_dir_name != "ace-run":
            continue
        by_project.setdefault(record.project_name, []).append(record)

    pairs: list[tuple[str, RunningAgentInfo]] = []
    for project_records in by_project.values():
        # Newest first, matching the existing ``sorted(..., reverse=True)``
        # walk in the per-directory loop.
        project_records.sort(key=lambda r: r.timestamp, reverse=True)
        kept = 0
        for record in project_records:
            if kept >= cap_per_project:
                break
            info = _done_info_from_record(record)
            if info is None:
                continue
            pairs.append((record.timestamp, info))
            kept += 1

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


def list_running_agents() -> list[RunningAgentInfo]:
    """List all currently running agents across all projects.

    Consumes one :func:`sase.core.agent_scan_facade.scan_agent_artifacts`
    snapshot for ``ace-run`` records, applies the current Python filters
    (parent-timestamp dedup, hidden-workflow skip, PID liveness), and
    returns most-recent-first.
    """
    snapshot = _scan_listing_snapshot()
    return _running_from_snapshot(snapshot)


def list_all_agents(
    *, cap_per_project: int = _DONE_AGENTS_CAP_PER_PROJECT
) -> list[RunningAgentInfo]:
    """List running agents plus recently-completed DONE/FAILED agents.

    Acquires one scan snapshot and computes both running and completed
    entries from it so the artifact walk happens at most once per call.
    Per-project completed cap and ordering match the previous direct-walk
    implementation.

    Returns:
        A list of RunningAgentInfo, sorted by start time (most recent
        first). Running agents always precede completed agents.
    """
    snapshot = _scan_listing_snapshot()
    running = _running_from_snapshot(snapshot)
    done = _done_from_snapshot(snapshot, cap_per_project=cap_per_project)
    return running + done


def kill_named_agent(name: str) -> _KillResult:
    """Kill a running agent by its assigned name.

    Locates the agent via find_named_agent(), derives the project context
    from its artifacts_dir, looks up the PID, sends SIGTERM to the process
    group, and cleans up the workspace claim or running marker.

    Args:
        name: The agent name to kill.

    Returns:
        A _KillResult with success status and a human-readable message.
    """
    agent = find_named_agent(name)
    if agent is None:
        return _KillResult(False, f"No agent found with name '{name}'")

    if agent.is_done:
        outcome_str = f" ({agent.outcome})" if agent.outcome else ""
        return _KillResult(False, f"Agent '{name}' already completed{outcome_str}")

    # Derive project context from artifacts_dir
    # Format: ~/.sase/projects/{project}/artifacts/ace-run/{timestamp}/
    artifacts_path = Path(agent.artifacts_dir)
    timestamp = artifacts_path.name
    project_name = artifacts_path.parent.parent.parent.name
    project_dir = artifacts_path.parent.parent.parent
    project_file = str(project_dir / f"{project_name}.gp")

    # Find PID
    pid: int | None = None
    is_home = project_name == "home"

    if is_home:
        # Home mode: read PID from running.json
        running_json = artifacts_path / "running.json"
        if running_json.exists():
            try:
                with open(running_json, encoding="utf-8") as f:
                    data = json.load(f)
                pid = data.get("pid")
            except (json.JSONDecodeError, OSError):
                pass
    else:
        # Non-home: scan RUNNING field for matching artifacts_timestamp
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                pid = claim.pid
                break

    if pid is None:
        return _KillResult(False, f"Could not find PID for agent '{name}'")

    # Kill the process group
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Already dead — continue with cleanup
    except PermissionError:
        return _KillResult(
            False,
            f"Permission denied killing agent '{name}' (PID {pid})",
        )

    # Cleanup
    if is_home:
        # Delete running.json (idempotent with runner's own cleanup)
        running_json = artifacts_path / "running.json"
        try:
            running_json.unlink(missing_ok=True)
        except OSError:
            pass
    else:
        # Release workspace (idempotent)
        from sase.running_field import get_claimed_workspaces, release_workspace

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                release_workspace(
                    project_file, claim.workspace_num, claim.workflow, claim.cl_name
                )
                break

    return _KillResult(True, f"Killed agent '{name}' (PID {pid})")
