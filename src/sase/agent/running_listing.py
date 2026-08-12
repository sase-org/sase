"""Snapshot-backed listing of active and recently completed agents."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Mapping

from sase.agent.names import is_process_alive
from sase.agent.status_buckets import EPIC_APPROVED_STATUS, valid_status_bucket
from sase.core.agent_clan_context import (
    ClanContextKey,
    clan_context_by_key,
    clan_context_for,
    effective_agent_tribe,
    effective_clan_attributes,
)
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
)
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import (
    is_root_user_agent_record,
    is_runner_slot_user_agent_record,
)
from sase.core.time import get_timezone


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
    status_bucket: str | None = None
    started_at: datetime | None = None
    duration_seconds: int | None = None
    artifacts_dir: str | None = None
    # Exact scheduler occupancy from the source scan record. ``None`` preserves
    # compatibility for integrations that construct this lightweight type.
    holds_runner_slot: bool | None = None
    # Canonical clan metadata from agent_meta.json. This is intentionally not
    # inferred from the agent's dotted name because ordinary hoods are not clans.
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    # Effective presentation-neutral tribe. Clan declarations/context take
    # precedence; standalone assignments remain unchanged for non-clan rows.
    tribe: str | None = None


class _RunningAgentListing(list[RunningAgentInfo]):
    """Agent rows plus the artifact snapshot used to build them.

    The list behavior preserves the long-standing public return contract while
    read-only integrations can derive related catalog entries without starting
    a second filesystem scan.
    """

    def __init__(
        self,
        values: list[RunningAgentInfo],
        *,
        artifact_snapshot: AgentArtifactScanWire,
    ) -> None:
        super().__init__(values)
        self.artifact_snapshot = artifact_snapshot


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


def active_status_for_record(record: AgentArtifactRecordWire) -> str:
    if record.waiting is not None:
        return "WAITING"
    pending_question = record.pending_question
    if pending_question is not None:
        request_path = pending_question.request_path
        if request_path:
            try:
                if Path(request_path).with_name("question_response.json").exists():
                    return "ANSWERED"
            except OSError:
                pass
        return "QUESTION"
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
    clan_contexts: Mapping[ClanContextKey, AgentClanContextWire],
) -> RunningAgentInfo | None:
    """Adapt a snapshot record into RunningAgentInfo, or skip via current filters."""
    meta = record.agent_meta
    if meta is None:
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

    status = active_status_for_record(record)
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
    context = clan_context_for(
        clan_contexts,
        agent_clan=meta.agent_clan,
        agent_clan_generation=meta.agent_clan_generation,
    )
    clan_tribe, _ = effective_clan_attributes(
        declared_tribe=meta.clan_tribe,
        declared_summary=meta.clan_summary,
        context=context,
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
        status_bucket=valid_status_bucket(meta.status_bucket),
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=record.artifact_dir,
        holds_runner_slot=bool(meta.run_started_at) and record.pending_question is None,
        agent_clan=meta.agent_clan,
        agent_clan_generation=meta.agent_clan_generation,
        clan_tribe=clan_tribe,
        tribe=effective_agent_tribe(
            standalone_tribe=meta.tribe,
            declared_clan_tribe=meta.clan_tribe,
            context=context,
        ),
    )


def _running_from_snapshot(
    snapshot: AgentArtifactScanWire,
) -> list[RunningAgentInfo]:
    """Build the running-agent list from *snapshot* using current Python filters."""
    now = datetime.now(get_timezone())
    workspace_cache: dict[str, list] = {}
    clan_contexts = clan_context_by_key(snapshot.clan_context)
    pairs: list[tuple[str, RunningAgentInfo]] = []

    for record in snapshot.records:
        is_root = is_root_user_agent_record(record)
        if not is_root and not _is_visible_runner_slot_child(record):
            continue
        info = _running_info_from_running_record(
            record,
            now=now,
            workspace_cache=workspace_cache,
            clan_contexts=clan_contexts,
        )
        if info is None:
            continue
        pairs.append((record.timestamp, info))

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


def _is_visible_runner_slot_child(record: AgentArtifactRecordWire) -> bool:
    """Return whether a non-root slot participant needs its own active row."""
    if not is_runner_slot_user_agent_record(record):
        return False
    meta = record.agent_meta
    if meta is None or not meta.parent_timestamp:
        return False
    holds_runner_slot = bool(meta.run_started_at) and record.pending_question is None
    queued_for_runner_slot = bool(
        record.waiting is not None and record.waiting.slot_requested_at
    )
    return holds_runner_slot or queued_for_runner_slot


def _done_info_from_record(
    record: AgentArtifactRecordWire,
    *,
    clan_contexts: Mapping[ClanContextKey, AgentClanContextWire],
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
    status_bucket = (
        valid_status_bucket(meta.status_bucket) if meta is not None else None
    )
    if status_bucket is None:
        status_bucket = valid_status_bucket(done.status_bucket)
    context = clan_context_for(
        clan_contexts,
        agent_clan=meta.agent_clan if meta is not None else None,
        agent_clan_generation=(
            meta.agent_clan_generation if meta is not None else None
        ),
    )
    clan_tribe, _ = effective_clan_attributes(
        declared_tribe=meta.clan_tribe if meta is not None else None,
        declared_summary=meta.clan_summary if meta is not None else None,
        context=context,
    )

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
        status_bucket=status_bucket,
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=record.artifact_dir,
        agent_clan=meta.agent_clan if meta is not None else None,
        agent_clan_generation=(
            meta.agent_clan_generation if meta is not None else None
        ),
        clan_tribe=clan_tribe,
        tribe=effective_agent_tribe(
            standalone_tribe=meta.tribe if meta is not None else None,
            declared_clan_tribe=(meta.clan_tribe if meta is not None else None),
            context=context,
        ),
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
    clan_contexts = clan_context_by_key(snapshot.clan_context)
    for project_records in by_project.values():
        # Newest first, matching the existing ``sorted(..., reverse=True)``
        # walk in the per-directory loop.
        project_records.sort(key=lambda r: r.timestamp, reverse=True)
        kept = 0
        for record in project_records:
            if kept >= cap_per_project:
                break
            info = _done_info_from_record(
                record,
                clan_contexts=clan_contexts,
            )
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
    (slot-relevant family-child projection, hidden-workflow skip, PID liveness), and
    returns most-recent-first.
    """
    snapshot = _scan_listing_snapshot()
    return _RunningAgentListing(
        _running_from_snapshot(snapshot),
        artifact_snapshot=snapshot,
    )


def list_all_agents(
    *, cap_per_project: int = _DONE_AGENTS_CAP_PER_PROJECT
) -> _RunningAgentListing:
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
    return _RunningAgentListing(
        running + done,
        artifact_snapshot=snapshot,
    )
