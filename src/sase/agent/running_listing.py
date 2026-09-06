"""Snapshot-backed listing of active and recently completed agents.

The implementation is split into focused modules, while this module remains
the stable import and monkeypatch surface for existing callers.
"""

from typing import Literal

from sase.agent.listing_snapshot import listing_snapshot, listing_trace
from sase.agent.names import is_process_alive
from sase.core.agent_scan_wire import AgentArtifactRecordWire, AgentArtifactScanWire

from ._running_listing_common import (
    active_status_for_record,
    finish_decode_trace,
    format_duration,
    is_monitor_member_meta,
    monitor_shell_field,
    monitor_sub_field,
    parse_iso_datetime,
    parse_started_at,
    record_is_live as record_is_live_impl,
    record_is_running_monitor,
    record_status_bucket,
    recorded_monitor_status,
    runner_slot_holder_dirs,
)
from ._running_listing_done import done_from_snapshot, done_info_from_record
from ._running_listing_running import (
    is_visible_monitor_record,
    is_visible_runner_slot_child,
    resolve_workspace_num,
    running_from_snapshot,
    running_info_from_running_record,
)
from ._running_listing_types import (
    DONE_AGENTS_CAP_PER_PROJECT,
    ListingDecodeCounters,
    RunningAgentInfo,
    RunningAgentListing,
)

_DONE_AGENTS_CAP_PER_PROJECT = DONE_AGENTS_CAP_PER_PROJECT
_ListingDecodeCounters = ListingDecodeCounters
_RunningAgentListing = RunningAgentListing
_done_from_snapshot = done_from_snapshot
_done_info_from_record = done_info_from_record
_finish_decode_trace = finish_decode_trace
_format_duration = format_duration
_is_monitor_member_meta = is_monitor_member_meta
_is_visible_monitor_record = is_visible_monitor_record
_is_visible_runner_slot_child = is_visible_runner_slot_child
_monitor_shell_field = monitor_shell_field
_monitor_sub_field = monitor_sub_field
_parse_iso_datetime = parse_iso_datetime
_parse_started_at = parse_started_at
_record_is_running_monitor = record_is_running_monitor
_record_status_bucket = record_status_bucket
_recorded_monitor_status = recorded_monitor_status
_resolve_workspace_num = resolve_workspace_num
_runner_slot_holder_dirs = runner_slot_holder_dirs
_running_info_from_running_record = running_info_from_running_record


def _record_is_live(record: AgentArtifactRecordWire) -> bool:
    """Compatibility wrapper around the process-liveness probe.

    Tests and integrations historically patched
    ``sase.agent.running_listing.is_process_alive``. Keeping this wrapper in
    the facade preserves that patch point after the implementation split.
    """
    return record_is_live_impl(record, process_alive=is_process_alive)


def _running_from_snapshot(
    snapshot: AgentArtifactScanWire,
    *,
    counters: ListingDecodeCounters | None = None,
) -> list[RunningAgentInfo]:
    return running_from_snapshot(
        snapshot,
        counters=counters,
        record_is_live=_record_is_live,
    )


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
        finish_decode_trace(
            extra,
            snapshot=snapshot,
            result_count=len(running),
            counters=counters,
        )
    return RunningAgentListing(
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
) -> RunningAgentListing:
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
        done = done_from_snapshot(snapshot, cap_per_project=cap_per_project)
        finish_decode_trace(
            extra,
            snapshot=snapshot,
            result_count=len(running) + len(done),
            counters=counters,
        )
    return RunningAgentListing(
        running + done,
        artifact_snapshot=snapshot,
        listing_state=state,
    )
