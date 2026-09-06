"""Build recently completed agent listing rows from artifact snapshots."""

from collections.abc import Mapping
from datetime import datetime

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
from sase.core.time import get_timezone
from sase.monitor_status import (
    DEFAULT_MONITOR_STOP_STATUS,
    clamp_monitor_status_or_default,
)

from ._running_listing_common import (
    format_duration,
    is_monitor_member_meta,
    monitor_shell_field,
    monitor_sub_field,
    parse_started_at,
    record_status_bucket,
    recorded_monitor_status,
)
from ._running_listing_types import RunningAgentInfo


def done_info_from_record(
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

    if meta is not None and meta.parent_timestamp and not is_monitor_member_meta(meta):
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
            done.status_label or monitor_shell_field(meta, "stop_status"),
            default=DEFAULT_MONITOR_STOP_STATUS,
        )
    elif outcome in {"failed", "epic_launch_failed"}:
        status = "FAILED"
    else:
        status = "DONE"

    started_at = parse_started_at(record.timestamp)
    duration = "?"
    duration_seconds: int | None = None
    if started_at is not None:
        if done.finished_at is not None:
            end = datetime.fromtimestamp(float(done.finished_at), get_timezone())
        else:
            end = datetime.now(get_timezone())
        duration_seconds = int((end - started_at).total_seconds())
        duration = format_duration(duration_seconds)

    name = (meta.name if meta is not None else None) or done.name
    pid = (meta.pid if meta is not None else None) or done.pid
    model = (meta.model if meta is not None else None) or done.model
    provider = (meta.llm_provider if meta is not None else None) or done.llm_provider
    approve = bool((meta.approve if meta is not None else False) or done.approve)
    done_monitor_exit_code = monitor_sub_field(done, "exit_code")
    status_bucket = record_status_bucket(
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
        monitor_id=monitor_shell_field(meta, "id"),
        monitor_state=monitor_shell_field(done, "state")
        or monitor_shell_field(meta, "state"),
        monitor_label=monitor_shell_field(meta, "label"),
        monitor_command=monitor_sub_field(meta, "command"),
        monitor_exit_code=(
            done_monitor_exit_code
            if done_monitor_exit_code is not None
            else monitor_sub_field(meta, "exit_code")
        ),
        monitor_start_status=recorded_monitor_status(
            monitor_shell_field(meta, "start_status")
        ),
        monitor_stop_status=recorded_monitor_status(
            done.status_label or monitor_shell_field(meta, "stop_status")
        ),
    )


def done_from_snapshot(
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
        # Newest first, matching the previous per-directory walk.
        project_records.sort(key=lambda r: r.timestamp, reverse=True)
        kept = 0
        for record in project_records:
            if kept >= cap_per_project:
                break
            info = done_info_from_record(
                record,
                clan_contexts=clan_contexts,
            )
            if info is None:
                continue
            pairs.append((record.timestamp, info))
            kept += 1

    pairs.sort(key=lambda x: x[0], reverse=True)
    return [info for _, info in pairs]


__all__ = [
    "done_from_snapshot",
    "done_info_from_record",
]
