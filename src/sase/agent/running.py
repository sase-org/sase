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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.agent.status_buckets import EPIC_APPROVED_STATUS
from sase.agent.user_kill import request_user_kill
from sase.agent.names import find_named_agent, is_process_alive
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.agent_artifact_index_lifecycle import (
    sync_dismissed_agent_artifact_index,
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import is_root_user_agent_record
from sase.core.time import get_timezone


@dataclass
class KillResult:
    """Result of a kill_named_agent() attempt."""

    success: bool
    message: str
    reason: str | None = None
    status: str | None = None
    pid: int | None = None
    changed: bool = False
    artifacts_dir: str | None = None
    project: str | None = None
    timestamp: str | None = None


_KillResult = KillResult


@dataclass
class RunningAgentInfo:
    """Summary info for an active or recently completed agent.

    ``status`` defaults to ``"RUNNING"`` for compatibility with direct
    construction in tests and integrations. Listing functions may emit
    ``"STARTING"``, ``"WAITING"``, ``"DONE"``, and ``"FAILED"`` as well.
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
    """Acquire one ace-run snapshot for the ChangeSpecI listing call sites."""
    # Local import: ``sase.core.agent_scan_facade`` pulls in the TUI loader
    # chain at import time (for the shared mtime cache), which transitively
    # imports ``sase.agent`` again. A module-level import here would
    # circle back through ``sase.agent.__init__`` and fail during startup.
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(
        sase_projects_dir(),
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


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=get_timezone())
    return parsed


def _active_status_for_record(record: AgentArtifactRecordWire) -> str:
    if record.waiting is not None:
        return "WAITING"
    meta = record.agent_meta
    if meta is not None and (meta.run_started_at or meta.wait_completed_at):
        return "RUNNING"
    return "STARTING"


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

    status = _active_status_for_record(record)
    started_at = _parse_iso_datetime(
        meta.run_started_at if status == "RUNNING" else None
    )
    if started_at is None:
        started_at = _parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if status == "RUNNING" and started_at is not None:
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
        status=status,
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
        if not is_root_user_agent_record(record):
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
    if outcome == "epic_approved":
        status = EPIC_APPROVED_STATUS
    elif outcome in {"failed", "epic_launch_failed"}:
        status = "FAILED"
    else:
        status = "DONE"

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


def kill_named_agent(name: str, *, exact_name: bool = False) -> _KillResult:
    """Kill a running agent by its assigned name.

    Locates the agent via find_named_agent(), derives the project context
    from its artifacts_dir, looks up the PID, sends SIGTERM to the process
    group, and cleans up the workspace claim or running marker.

    Args:
        name: The agent name to kill.
        exact_name: When true, reject workflow-name matches and only kill an
            artifact whose ``agent_meta.json`` name exactly matches ``name``.

    Returns:
        A KillResult with success status and a human-readable message.
    """
    agent = find_named_agent(name)
    if agent is None:
        return _KillResult(
            False,
            f"No agent found with name '{name}'",
            reason="not_found",
            status="not_found",
        )

    if exact_name and not _agent_meta_name_matches(agent.artifacts_dir, name):
        return _KillResult(
            False,
            f"No agent found with name '{name}'",
            reason="not_found",
            status="not_found",
        )

    if agent.is_done:
        outcome_str = f" ({agent.outcome})" if agent.outcome else ""
        return _KillResult(
            False,
            f"Agent '{name}' already completed{outcome_str}",
            reason="already_completed",
            status="already_completed",
            artifacts_dir=agent.artifacts_dir,
        )

    # Derive project context from artifacts_dir.
    from sase.ace.changespec.project_spec_path import preferred_project_spec_path
    from sase.core.agent_artifact_paths import parse_agent_artifact_path

    artifacts_path = Path(agent.artifacts_dir)
    path_info = parse_agent_artifact_path(artifacts_path)
    if path_info is None:
        timestamp = artifacts_path.name
        project_dir = artifacts_path.parent.parent.parent
        project_name = project_dir.name
    else:
        timestamp = path_info.timestamp
        project_name = path_info.project_name
        project_dir = artifacts_path
        while project_dir.name != project_name and project_dir.parent != project_dir:
            project_dir = project_dir.parent
    project_file = preferred_project_spec_path(str(project_dir), project_name)

    # Find PID
    pid: int | None = None
    cl_name: str | None = None
    is_home = project_name == "home"

    if is_home:
        # Home mode: read PID from running.json
        pid = _read_pid_from_running_marker(artifacts_path)
        cl_name = _read_cl_name_from_meta(artifacts_path)
    else:
        # Non-home: scan RUNNING field for matching artifacts_timestamp
        from sase.running_field import get_claimed_workspaces

        for claim in get_claimed_workspaces(project_file):
            if claim.artifacts_timestamp == timestamp:
                pid = _valid_pid(claim.pid)
                cl_name = claim.cl_name
                break
        if cl_name is None:
            cl_name = _read_cl_name_from_artifacts(artifacts_path)

    if pid is None:
        meta = _read_agent_meta(artifacts_path)
        meta_pid = _valid_pid(meta.get("pid")) if meta is not None else None
        if (
            meta is not None
            and meta_pid is not None
            and is_process_alive(meta, artifacts_path)
        ):
            pid = meta_pid
            if cl_name is None:
                cl_name = _read_cl_name_from_artifacts(artifacts_path)
        else:
            if not is_home:
                _release_workspace_claim(project_file, timestamp)
            _remove_agent_state_markers(
                artifacts_path,
                remove_running=True,
                remove_waiting=True,
            )
            _record_dismissal(cl_name, timestamp)
            _dismiss_agent_notifications(cl_name, timestamp)
            return _KillResult(
                True,
                f"Agent '{name}' was not running; cleaned up stale state",
                status="not_running",
                changed=True,
                artifacts_dir=agent.artifacts_dir,
                project=project_name,
                timestamp=timestamp,
            )

    kill_result = request_user_kill(
        pid,
        artifacts_dir=artifacts_path,
        source="agents_kill",
        wait=True,
    )
    if not kill_result.success and kill_result.status == "permission_denied":
        return _KillResult(
            False,
            f"Permission denied killing agent '{name}' (PID {pid})",
            reason="permission_denied",
            status="permission_denied",
            pid=pid,
            artifacts_dir=agent.artifacts_dir,
            project=project_name,
            timestamp=timestamp,
        )
    status = kill_result.status

    # Cleanup
    if is_home:
        _remove_agent_state_markers(
            artifacts_path,
            remove_running=True,
            remove_waiting=_kill_result_confirms_dead(status),
        )
    else:
        _release_workspace_claim(project_file, timestamp)
        if _kill_result_confirms_dead(status):
            _remove_agent_state_markers(
                artifacts_path,
                remove_running=False,
                remove_waiting=True,
            )

    _record_dismissal(cl_name, timestamp)
    _dismiss_agent_notifications(cl_name, timestamp)

    return _KillResult(
        True,
        f"Killed agent '{name}' (PID {pid})",
        status=status,
        pid=pid,
        changed=True,
        artifacts_dir=agent.artifacts_dir,
        project=project_name,
        timestamp=timestamp,
    )


def _valid_pid(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 1 else None


def _read_json_dict(path: Path) -> dict[str, object] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _read_agent_meta(artifacts_path: Path) -> dict[str, object] | None:
    return _read_json_dict(artifacts_path / "agent_meta.json")


def _read_pid_from_running_marker(artifacts_path: Path) -> int | None:
    data = _read_json_dict(artifacts_path / "running.json")
    return _valid_pid(data.get("pid")) if data is not None else None


def _read_str_field(data: dict[str, object] | None, *keys: str) -> str | None:
    if data is None:
        return None
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _read_cl_name_from_artifacts(artifacts_path: Path) -> str | None:
    meta_value = _read_str_field(
        _read_agent_meta(artifacts_path),
        "cl_name",
        "changespec_name",
    )
    if meta_value is not None:
        return meta_value

    waiting_value = _read_str_field(
        _read_json_dict(artifacts_path / "waiting.json"),
        "cl_name",
    )
    if waiting_value is not None:
        return waiting_value

    workflow_state = _read_json_dict(artifacts_path / "workflow_state.json")
    context = workflow_state.get("context") if workflow_state is not None else None
    if isinstance(context, dict):
        return _read_str_field(context, "cl_name")
    return None


def _release_workspace_claim(project_file: str, timestamp: str) -> None:
    from sase.running_field import get_claimed_workspaces, release_workspace

    for claim in get_claimed_workspaces(project_file):
        if claim.artifacts_timestamp == timestamp:
            release_workspace(
                project_file, claim.workspace_num, claim.workflow, claim.cl_name
            )
            break


def _kill_result_confirms_dead(status: str | None) -> bool:
    return status in {"already_stopped", "killed"}


def _remove_agent_state_markers(
    artifacts_path: Path,
    *,
    remove_running: bool,
    remove_waiting: bool,
) -> bool:
    marker_names: list[str] = []
    if remove_waiting:
        marker_names.append("waiting.json")
    if remove_running:
        marker_names.append("running.json")

    changed = False
    for marker_name in marker_names:
        try:
            (artifacts_path / marker_name).unlink()
        except FileNotFoundError:
            continue
        except OSError:
            continue
        else:
            changed = True

    if changed:
        try:
            update_agent_artifact_index_for_marker_mutation(artifacts_path)
        except Exception:
            pass
    return changed


def _read_cl_name_from_meta(artifacts_path: Path) -> str | None:
    return _read_str_field(_read_agent_meta(artifacts_path), "cl_name")


def _record_dismissal(cl_name: str | None, raw_suffix: str) -> None:
    """Add the killed agent to the persistent dismissed-agents index.

    Failure to write the index must never flip a successful kill into a
    failure — the kill itself already happened.
    """
    try:
        from sase.ace.dismissed_agents import (
            load_dismissed_agents,
            save_dismissed_agents,
        )
        from sase.ace.tui.models.agent import AgentType

        identity = (AgentType.RUNNING, cl_name or "unknown", raw_suffix)
        dismissed = load_dismissed_agents()
        if identity not in dismissed:
            dismissed.add(identity)
            if save_dismissed_agents(dismissed):
                sync_dismissed_agent_artifact_index(dismissed, added={identity})
    except Exception:
        pass


def _dismiss_agent_notifications(cl_name: str | None, raw_suffix: str) -> None:
    """Best-effort notification cleanup after a successful named-agent kill."""
    if not cl_name:
        return
    try:
        from sase.notifications import dismiss_notifications_matching_agents

        dismiss_notifications_matching_agents(
            [{"cl_name": cl_name, "raw_suffix": raw_suffix}]
        )
    except Exception:
        # The process is already dead (or confirmed stale), so notification
        # storage failures must not turn the successful kill into an error.
        pass


def _agent_meta_name_matches(artifacts_dir: str, expected_name: str) -> bool:
    try:
        with open(Path(artifacts_dir) / "agent_meta.json", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(data, dict) and data.get("name") == expected_name
