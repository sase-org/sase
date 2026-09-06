"""Build active running-agent listing rows from artifact snapshots."""

from collections.abc import Mapping
from datetime import datetime

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
    is_root_user_agent_record,
    is_runner_slot_occupying_record,
    is_runner_slot_user_agent_record,
)
from sase.core.time import get_timezone

from ._running_listing_common import (
    RecordLiveProbe,
    format_duration,
    is_monitor_member_meta,
    monitor_shell_field,
    monitor_sub_field,
    parse_iso_datetime,
    parse_started_at,
    record_is_live as default_record_is_live,
    record_is_running_monitor,
    record_status_bucket,
    recorded_monitor_status,
    runner_slot_holder_dirs,
    active_status_for_record,
)
from ._running_listing_types import ListingDecodeCounters, RunningAgentInfo


def resolve_workspace_num(
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


def running_info_from_running_record(
    record: AgentArtifactRecordWire,
    *,
    now: datetime,
    workspace_cache: dict[str, list],
    clan_contexts: Mapping[ClanContextKey, AgentClanContextWire],
    holder_dirs: frozenset[str],
    record_is_live: RecordLiveProbe = default_record_is_live,
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
    started_at = parse_iso_datetime(
        meta.run_started_at
        if status == "RUNNING" or record_is_running_monitor(record)
        else None
    )
    if started_at is None:
        started_at = parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if record_is_running_monitor(record):
        duration_seconds = (
            int((now - started_at).total_seconds()) if started_at is not None else None
        )
        duration = (
            format_duration(duration_seconds) if duration_seconds is not None else "?"
        )
    elif status == "RUNNING" and started_at is not None:
        duration_seconds = int((now - started_at).total_seconds())
        duration = format_duration(duration_seconds)

    workspace_num = resolve_workspace_num(
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
        status_bucket=record_status_bucket(meta.status_bucket, meta, None),
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
        monitor_id=monitor_shell_field(meta, "id"),
        monitor_state=monitor_shell_field(meta, "state"),
        monitor_label=monitor_shell_field(meta, "label"),
        monitor_command=monitor_sub_field(meta, "command"),
        monitor_exit_code=monitor_sub_field(meta, "exit_code"),
        monitor_start_status=recorded_monitor_status(
            monitor_shell_field(meta, "start_status")
        ),
        monitor_stop_status=recorded_monitor_status(
            monitor_shell_field(meta, "stop_status")
        ),
    )


def running_from_snapshot(
    snapshot: AgentArtifactScanWire,
    *,
    counters: ListingDecodeCounters | None = None,
    record_is_live: RecordLiveProbe | None = None,
) -> list[RunningAgentInfo]:
    """Build the running-agent list from *snapshot* using current Python filters."""
    base_record_is_live = (
        default_record_is_live if record_is_live is None else record_is_live
    )
    effective_record_is_live = base_record_is_live
    if counters is not None:

        def counted_record_is_live(record: AgentArtifactRecordWire) -> bool:
            counters.liveness_checks += 1
            return base_record_is_live(record)

        effective_record_is_live = counted_record_is_live

    now = datetime.now(get_timezone())
    workspace_cache: dict[str, list] = {}
    clan_contexts = clan_context_by_key(snapshot.clan_context)
    holder_dirs = runner_slot_holder_dirs(
        snapshot.records,
        record_is_live=effective_record_is_live,
    )
    pairs: list[tuple[str, RunningAgentInfo]] = []

    for record in snapshot.records:
        is_root = is_root_user_agent_record(record)
        if (
            not is_root
            and not is_visible_runner_slot_child(
                record,
                record_is_live=effective_record_is_live,
            )
            and not is_visible_monitor_record(record)
        ):
            continue
        info = running_info_from_running_record(
            record,
            holder_dirs=holder_dirs,
            now=now,
            workspace_cache=workspace_cache,
            clan_contexts=clan_contexts,
            record_is_live=effective_record_is_live,
        )
        if info is None:
            continue
        pairs.append((record.timestamp, info))

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


def is_visible_runner_slot_child(
    record: AgentArtifactRecordWire,
    *,
    record_is_live: RecordLiveProbe = default_record_is_live,
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


def is_visible_monitor_record(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return bool(
        record.workflow_dir_name == "ace-run"
        and meta is not None
        and monitor_shell_field(meta, "id")
        and is_monitor_member_meta(meta)
        and not record.has_done_marker
    )


__all__ = [
    "is_visible_monitor_record",
    "is_visible_runner_slot_child",
    "resolve_workspace_num",
    "running_from_snapshot",
    "running_info_from_running_record",
]
