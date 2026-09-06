"""Snapshot-backed listing of active and recently completed agents."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from typing import Literal

from sase.agent.listing_snapshot import (
    AgentListingLoadState,
    listing_trace,
    listing_snapshot,
    snapshot_trace_bytes,
)
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
    AgentArtifactScanWire,
    AgentClanContextWire,
)
from sase.core.runner_slots import (
    group_records_by_runner_slot_family,
    is_root_user_agent_record,
    is_runner_slot_occupying_record,
    is_runner_slot_user_agent_record,
)
from sase.core.time import get_timezone
from sase.monitor_state import is_monitor_member_role, monitor_state_bucket
from sase.monitor_status import (
    DEFAULT_MONITOR_START_STATUS,
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)


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
    agent_family: str | None = None
    agent_family_role: str | None = None
    role_suffix: str | None = None
    monitor_id: str | None = None
    monitor_state: str | None = None
    monitor_label: str | None = None
    monitor_command: str | None = None
    monitor_exit_code: int | None = None
    monitor_start_status: str | None = None
    monitor_stop_status: str | None = None

    @property
    def is_monitor(self) -> bool:
        """Whether this row is a monitor member rather than its starter."""
        return is_monitor_member_role(self.agent_family_role, self.role_suffix)


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
        listing_state: AgentListingLoadState | None = None,
    ) -> None:
        super().__init__(values)
        self.artifact_snapshot = artifact_snapshot
        self.listing_state = listing_state


@dataclass
class _ListingDecodeCounters:
    liveness_checks: int = 0


_DONE_AGENTS_CAP_PER_PROJECT = 50


def _finish_decode_trace(
    extra: dict[str, Any],
    *,
    snapshot: AgentArtifactScanWire,
    result_count: int,
    counters: _ListingDecodeCounters,
) -> None:
    extra.update(
        {
            "record_count": len(snapshot.records),
            "result_count": result_count,
            "liveness_checks": counters.liveness_checks,
        }
    )
    snapshot_bytes = snapshot_trace_bytes(snapshot)
    if snapshot_bytes is not None:
        extra["decode_bytes"] = snapshot_bytes


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


def _record_is_live(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    pid = None if meta is None else meta.pid
    if pid is None and record.running is not None:
        pid = record.running.pid
    liveness: dict[str, object] = {}
    if pid is not None:
        liveness["pid"] = pid
    if meta is not None:
        if meta.stopped_at is not None:
            liveness["stopped_at"] = meta.stopped_at
        process_identity = getattr(meta, "process_identity", None)
        if process_identity is not None:
            liveness["process_identity"] = process_identity
    if (
        "process_identity" not in liveness
        and record.running is not None
        and getattr(record.running, "process_identity", None) is not None
    ):
        liveness["process_identity"] = record.running.process_identity
    return is_process_alive(liveness, Path(record.artifact_dir))


def _runner_slot_holder_dirs(
    records: Iterable[AgentArtifactRecordWire],
    *,
    record_is_live: Callable[[AgentArtifactRecordWire], bool] = _record_is_live,
) -> frozenset[str]:
    """Return the artifact_dir of each shell credited with holding a slot.

    Mirrors `running_agent_slot_count`'s per-family dedup so this listing's
    summed `holds_runner_slot` flags match the admission gate's occupancy
    count for the same snapshot: a serial family holds one slot no matter
    how many of its shells are simultaneously live (an overlapping root and
    a successor mid-handoff, for instance), so only one representative
    shell is credited per family. Each live parallel member still holds its
    own slot and is credited individually.
    """
    holders: set[str] = set()
    for group in group_records_by_runner_slot_family(records).values():
        serial_holder: str | None = None
        for candidate in group:
            if not is_runner_slot_occupying_record(candidate, record_is_live):
                continue
            meta = candidate.agent_meta
            if meta is not None and meta.agent_family_parallel:
                holders.add(candidate.artifact_dir)
            elif serial_holder is None:
                serial_holder = candidate.artifact_dir
        if serial_holder is not None:
            holders.add(serial_holder)
    return frozenset(holders)


def _recorded_monitor_status(value: str | None) -> str | None:
    """Clamp a stored monitor label, or return ``None`` when missing/invalid."""
    if value is None:
        return None
    return clamp_monitor_status_or_default(value, default="") or None


def _is_monitor_member_meta(meta: object | None) -> bool:
    return bool(
        meta is not None
        and is_monitor_member_role(
            getattr(meta, "agent_family_role", None),
            getattr(meta, "role_suffix", None),
        )
    )


def _monitor_shell_field(source: object | None, field: str) -> Any:
    """Read a shared ``family_shell`` field, only when *source* is a monitor shell."""
    shell = getattr(source, "family_shell", None)
    if shell is not None and getattr(shell, "kind", None) == "monitor":
        return getattr(shell, field, None)
    return None


def _monitor_sub_field(source: object | None, field: str) -> Any:
    """Read a monitor-only ``family_shell.monitor`` field."""
    shell = getattr(source, "family_shell", None)
    if shell is not None and getattr(shell, "kind", None) == "monitor":
        monitor = getattr(shell, "monitor", None)
        if monitor is not None:
            return getattr(monitor, field, None)
    return None


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
    if meta is not None and _is_monitor_member_meta(meta):
        if meta.run_started_at or meta.wait_completed_at:
            return clamp_monitor_status_or_default(
                _monitor_shell_field(meta, "start_status"),
                default=DEFAULT_MONITOR_START_STATUS,
            )
        return "STARTING"
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
    holder_dirs: frozenset[str],
    record_is_live: Callable[[AgentArtifactRecordWire], bool] = _record_is_live,
) -> RunningAgentInfo | None:
    """Adapt a snapshot record into RunningAgentInfo, or skip via current filters."""
    meta = record.agent_meta
    if meta is None:
        return None
    wf_state = record.workflow_state
    if wf_state is not None and not wf_state.appears_as_agent:
        return None

    if not record_is_live(record):
        return None

    status = active_status_for_record(record)
    started_at = _parse_iso_datetime(
        meta.run_started_at
        if status == "RUNNING" or _record_is_running_monitor(record)
        else None
    )
    if started_at is None:
        started_at = _parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if _record_is_running_monitor(record):
        duration_seconds = (
            int((now - started_at).total_seconds()) if started_at is not None else None
        )
        duration = (
            _format_duration(duration_seconds) if duration_seconds is not None else "?"
        )
    elif status == "RUNNING" and started_at is not None:
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
        status_bucket=_record_status_bucket(meta.status_bucket, meta, None),
        started_at=started_at,
        duration_seconds=duration_seconds,
        artifacts_dir=record.artifact_dir,
        holds_runner_slot=record.artifact_dir in holder_dirs,
        agent_clan=meta.agent_clan,
        agent_clan_generation=meta.agent_clan_generation,
        clan_tribe=clan_tribe,
        tribe=effective_agent_tribe(
            standalone_tribe=meta.tribe,
            declared_clan_tribe=meta.clan_tribe,
            context=context,
        ),
        agent_family=meta.agent_family,
        agent_family_role=meta.agent_family_role,
        role_suffix=meta.role_suffix,
        monitor_id=_monitor_shell_field(meta, "id"),
        monitor_state=_monitor_shell_field(meta, "state"),
        monitor_label=_monitor_shell_field(meta, "label"),
        monitor_command=_monitor_sub_field(meta, "command"),
        monitor_exit_code=_monitor_sub_field(meta, "exit_code"),
        monitor_start_status=_recorded_monitor_status(
            _monitor_shell_field(meta, "start_status")
        ),
        monitor_stop_status=_recorded_monitor_status(
            _monitor_shell_field(meta, "stop_status")
        ),
    )


def _running_from_snapshot(
    snapshot: AgentArtifactScanWire,
    *,
    counters: _ListingDecodeCounters | None = None,
) -> list[RunningAgentInfo]:
    """Build the running-agent list from *snapshot* using current Python filters."""
    record_is_live: Callable[[AgentArtifactRecordWire], bool] = _record_is_live
    if counters is not None:

        def counted_record_is_live(record: AgentArtifactRecordWire) -> bool:
            counters.liveness_checks += 1
            return _record_is_live(record)

        record_is_live = counted_record_is_live

    now = datetime.now(get_timezone())
    workspace_cache: dict[str, list] = {}
    clan_contexts = clan_context_by_key(snapshot.clan_context)
    holder_dirs = _runner_slot_holder_dirs(
        snapshot.records,
        record_is_live=record_is_live,
    )
    pairs: list[tuple[str, RunningAgentInfo]] = []

    for record in snapshot.records:
        is_root = is_root_user_agent_record(record)
        if (
            not is_root
            and not _is_visible_runner_slot_child(
                record,
                record_is_live=record_is_live,
            )
            and not _is_visible_monitor_record(record)
        ):
            continue
        info = _running_info_from_running_record(
            record,
            holder_dirs=holder_dirs,
            now=now,
            workspace_cache=workspace_cache,
            clan_contexts=clan_contexts,
            record_is_live=record_is_live,
        )
        if info is None:
            continue
        pairs.append((record.timestamp, info))

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


def _is_visible_runner_slot_child(
    record: AgentArtifactRecordWire,
    *,
    record_is_live: Callable[[AgentArtifactRecordWire], bool] = _record_is_live,
) -> bool:
    """Return whether a non-root slot participant needs its own active row.

    Visibility follows *occupancy*, not admission eligibility: a serial
    child -- a monitor member, or a post-handoff follow-up agent whose
    ``parent_timestamp`` names a dead starter -- can be the shell currently
    holding its family's slot even though it never itself waits at the
    admission gate (`is_runner_slot_user_agent_record` is False for it). A
    live shell must never go missing from `sase agent list` just because it
    is not the one that happened to claim the slot. The queued branch stays
    admission-gated: only a root or a live parallel member ever waits.
    """
    meta = record.agent_meta
    if meta is None or not meta.parent_timestamp:
        return False
    if is_runner_slot_occupying_record(record, record_is_live):
        return True
    return bool(
        is_runner_slot_user_agent_record(record)
        and record.waiting is not None
        and record.waiting.slot_requested_at
    )


def _is_visible_monitor_record(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return bool(
        record.workflow_dir_name == "ace-run"
        and meta is not None
        and _monitor_shell_field(meta, "id")
        and _is_monitor_member_meta(meta)
        and not record.has_done_marker
    )


def _record_is_running_monitor(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return bool(
        meta is not None
        and _monitor_shell_field(meta, "id")
        and _is_monitor_member_meta(meta)
        and _monitor_shell_field(meta, "state") == "running"
    )


def _record_status_bucket(
    raw_bucket: str | None,
    meta: object | None,
    done: object | None,
) -> str | None:
    monitor_state = _monitor_shell_field(done, "state") or _monitor_shell_field(
        meta, "state"
    )
    if _is_monitor_member_meta(meta):
        return monitor_state_bucket(monitor_state)
    return valid_status_bucket(raw_bucket)


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

    if meta is not None and meta.parent_timestamp and not _is_monitor_member_meta(meta):
        return None

    wf_state = record.workflow_state
    if wf_state is not None and not wf_state.appears_as_agent:
        return None

    outcome = done.outcome or "completed"
    if outcome == "noop":
        return None
    if outcome == "epic_approved":
        status = EPIC_APPROVED_STATUS
    elif outcome == "monitored":
        status = clamp_monitor_status_or_default(
            done.status_label or _monitor_shell_field(meta, "stop_status"),
            default=DEFAULT_MONITOR_STOP_STATUS,
        )
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
    done_monitor_exit_code = _monitor_sub_field(done, "exit_code")
    status_bucket = _record_status_bucket(
        meta.status_bucket if meta is not None else None,
        meta,
        done,
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
        agent_family=meta.agent_family if meta is not None else None,
        agent_family_role=meta.agent_family_role if meta is not None else None,
        role_suffix=meta.role_suffix if meta is not None else None,
        monitor_id=_monitor_shell_field(meta, "id"),
        monitor_state=_monitor_shell_field(done, "state")
        or _monitor_shell_field(meta, "state"),
        monitor_label=_monitor_shell_field(meta, "label"),
        monitor_command=_monitor_sub_field(meta, "command"),
        monitor_exit_code=(
            done_monitor_exit_code
            if done_monitor_exit_code is not None
            else _monitor_sub_field(meta, "exit_code")
        ),
        monitor_start_status=_recorded_monitor_status(
            _monitor_shell_field(meta, "start_status")
        ),
        monitor_stop_status=_recorded_monitor_status(
            done.status_label or _monitor_shell_field(meta, "stop_status")
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


def list_running_agents(
    *,
    project: str | None = None,
    index_freshness: Literal["cached", "revalidate"] = "cached",
    requested_limit: int | None = None,
) -> list[RunningAgentInfo]:
    """List all currently running agents across all projects.

    Consumes one :func:`sase.core.agent_scan_facade.scan_agent_artifacts`
    snapshot for ``ace-run`` records, applies the current Python filters
    (slot-relevant family-child projection, hidden-workflow skip, PID liveness), and
    returns most-recent-first.
    """
    snapshot, state = listing_snapshot(
        project=project,
        index_freshness=index_freshness,
        requested_limit=requested_limit,
    )
    counters = _ListingDecodeCounters()
    with listing_trace("agent_listing.decode", mode="running") as extra:
        running = _running_from_snapshot(snapshot, counters=counters)
        _finish_decode_trace(
            extra,
            snapshot=snapshot,
            result_count=len(running),
            counters=counters,
        )
    return _RunningAgentListing(
        running,
        artifact_snapshot=snapshot,
        listing_state=state,
    )


def list_all_agents(
    *,
    cap_per_project: int = _DONE_AGENTS_CAP_PER_PROJECT,
    project: str | None = None,
    index_freshness: Literal["cached", "revalidate"] = "cached",
    requested_limit: int | None = None,
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
    snapshot, state = listing_snapshot(
        project=project,
        index_freshness=index_freshness,
        requested_limit=requested_limit,
    )
    counters = _ListingDecodeCounters()
    with listing_trace("agent_listing.decode", mode="all") as extra:
        running = _running_from_snapshot(snapshot, counters=counters)
        done = _done_from_snapshot(snapshot, cap_per_project=cap_per_project)
        _finish_decode_trace(
            extra,
            snapshot=snapshot,
            result_count=len(running) + len(done),
            counters=counters,
        )
    return _RunningAgentListing(
        running + done,
        artifact_snapshot=snapshot,
        listing_state=state,
    )
