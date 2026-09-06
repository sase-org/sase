"""Bounded artifact snapshots for local agent listing surfaces."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
    agent_scan_wire_to_json_dict,
)
from sase.core.paths import sase_projects_dir

_LISTING_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=False,
    only_workflow_dirs=("ace-run",),
)
_LISTING_ACTIVE_LIMIT = 1000
_LISTING_RECENT_COMPLETED_LIMIT = 200


@dataclass(frozen=True)
class AgentListingLoadState:
    """Artifact-source diagnostics for local CLI/mobile agent listings."""

    artifact_source: Literal["artifact_index", "source_scan"]
    used_artifact_index: bool
    index_error: str | None = None
    repair_recommended: bool = False
    repair_reason: str | None = None
    record_count: int | None = None
    bounded_prefix: bool = False
    requested_limit: int | None = None
    returned_count: int | None = None
    has_more: bool = False


def _scan_listing_snapshot(
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactScanWire:
    """Acquire one ace-run snapshot for local listing call sites."""
    from sase.core.agent_scan_facade import scan_agent_artifacts

    return scan_agent_artifacts(
        sase_projects_dir(),
        options or _LISTING_SCAN_OPTIONS,
    )


def listing_snapshot(
    *,
    project: str | None = None,
    index_freshness: Literal["cached", "revalidate"] = "cached",
    requested_limit: int | None = None,
) -> tuple[AgentArtifactScanWire, AgentListingLoadState]:
    """Return a bounded local listing snapshot, preferring the artifact index."""
    normalized_project = _normalized_project_filter(project)
    scan_options = _listing_scan_options(project=normalized_project)
    fallback_options = _listing_scan_options(
        project=normalized_project,
        recent_completed_limit=_LISTING_RECENT_COMPLETED_LIMIT,
        newest_first=True,
    )
    source_scans = 0
    index_queries = 0

    with listing_trace(
        "agent_listing.snapshot",
        project=normalized_project,
        freshness=index_freshness,
        requested_limit=requested_limit,
    ) as extra:
        try:
            from sase.core.agent_scan_facade import (
                default_agent_artifact_index_path,
                query_agent_artifact_index,
            )

            index_path = default_agent_artifact_index_path()
            if index_path.is_file():
                index_queries += 1
                snapshot = query_agent_artifact_index(
                    index_path,
                    sase_projects_dir(),
                    query=AgentArtifactIndexQueryWire(
                        include_active=True,
                        include_recent_completed=True,
                        include_full_history=False,
                        active_limit=_LISTING_ACTIVE_LIMIT,
                        recent_completed_limit=_LISTING_RECENT_COMPLETED_LIMIT,
                        include_hidden=False,
                        freshness=index_freshness,
                        record_shape="list",
                        window_limit=requested_limit,
                        candidate_filter=_project_candidate_filter(normalized_project),
                    ),
                    options=scan_options,
                )
                state = _listing_state_from_index_snapshot(snapshot)
                if _should_use_empty_index_fallback(snapshot, state, index_path):
                    source_scans += 1
                    snapshot = _scan_listing_snapshot(fallback_options)
                    state = AgentListingLoadState(
                        artifact_source="source_scan",
                        used_artifact_index=False,
                        repair_recommended=True,
                        repair_reason="artifact_index_empty_bounded_fallback",
                        record_count=len(snapshot.records),
                    )
                _finish_snapshot_trace(
                    extra,
                    snapshot=snapshot,
                    state=state,
                    index_queries=index_queries,
                    source_scans=source_scans,
                )
                return snapshot, state
        except (ImportError, AttributeError, OSError, ValueError, RuntimeError) as exc:
            source_scans += 1
            snapshot = _scan_listing_snapshot(fallback_options)
            state = AgentListingLoadState(
                artifact_source="source_scan",
                used_artifact_index=False,
                index_error=str(exc),
                repair_recommended=True,
                repair_reason="artifact_index_query_failed_bounded_fallback",
                record_count=len(snapshot.records),
            )
            _finish_snapshot_trace(
                extra,
                snapshot=snapshot,
                state=state,
                index_queries=index_queries,
                source_scans=source_scans,
            )
            return snapshot, state

        source_scans += 1
        snapshot = _scan_listing_snapshot(fallback_options)
        state = AgentListingLoadState(
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
            record_count=len(snapshot.records),
        )
        _finish_snapshot_trace(
            extra,
            snapshot=snapshot,
            state=state,
            index_queries=index_queries,
            source_scans=source_scans,
        )
        return snapshot, state


def snapshot_trace_bytes(snapshot: AgentArtifactScanWire) -> int | None:
    """Return the JSON payload size for trace-only decode-byte counters."""
    if not _listing_trace_enabled():
        return None
    payload = agent_scan_wire_to_json_dict(snapshot)
    return len(json.dumps(payload, sort_keys=True).encode("utf-8"))


def _listing_scan_options(
    *,
    project: str | None,
    recent_completed_limit: int | None = None,
    newest_first: bool = False,
) -> AgentArtifactScanOptionsWire:
    return replace(
        _LISTING_SCAN_OPTIONS,
        max_records=recent_completed_limit,
        newest_first=newest_first,
        only_projects=(project,) if project else (),
    )


def _normalized_project_filter(project: str | None) -> str | None:
    if project is None:
        return None
    normalized = project.strip()
    return normalized or None


def _project_candidate_filter(project: str | None) -> dict[str, object] | None:
    if project is None:
        return None
    return {"kind": "equals", "field": "project", "value": project}


def _listing_state_from_index_snapshot(
    snapshot: AgentArtifactScanWire,
) -> AgentListingLoadState:
    index_window = snapshot.index_window
    return AgentListingLoadState(
        artifact_source="artifact_index",
        used_artifact_index=True,
        record_count=len(snapshot.records),
        bounded_prefix=index_window is not None,
        requested_limit=None if index_window is None else index_window.requested_limit,
        returned_count=(
            None if index_window is None else index_window.returned_record_count
        ),
        has_more=False if index_window is None else index_window.has_more,
    )


def _should_use_empty_index_fallback(
    snapshot: AgentArtifactScanWire,
    state: AgentListingLoadState,
    index_path: Path,
) -> bool:
    if snapshot.records:
        return False
    if state.returned_count not in (None, 0):
        return False
    return _artifact_index_has_no_rows(index_path)


def _artifact_index_has_no_rows(index_path: Path) -> bool:
    try:
        from sase.core.agent_scan_facade import agent_artifact_index_status

        status = agent_artifact_index_status(index_path)
    except (ImportError, AttributeError, OSError, ValueError, RuntimeError):
        return False
    return status.agent_artifacts_rows == 0


def listing_trace(
    span: str,
    **counters: Any,
) -> AbstractContextManager[dict[str, Any]]:
    try:
        from sase.ace.tui.util.trace import tui_trace
    except (ImportError, RuntimeError):
        return nullcontext({})
    return tui_trace(span, **counters)


def _listing_trace_enabled() -> bool:
    try:
        from sase.ace.tui.util.trace import is_enabled
    except (ImportError, RuntimeError):
        return False
    return is_enabled()


def _finish_snapshot_trace(
    extra: dict[str, Any],
    *,
    snapshot: AgentArtifactScanWire,
    state: AgentListingLoadState,
    index_queries: int,
    source_scans: int,
) -> None:
    index_window = snapshot.index_window
    extra.update(
        {
            "artifact_source": state.artifact_source,
            "used_artifact_index": state.used_artifact_index,
            "source_scans": source_scans,
            "index_queries": index_queries,
            "record_count": len(snapshot.records),
            "projects_visited": snapshot.stats.projects_visited,
            "artifact_dirs_visited": snapshot.stats.artifact_dirs_visited,
            "marker_files_parsed": snapshot.stats.marker_files_parsed,
            "json_decode_errors": snapshot.stats.json_decode_errors,
            "os_errors": snapshot.stats.os_errors,
            "candidate_count": (
                len(snapshot.records)
                if index_window is None
                else index_window.selected_candidate_count
            ),
            "active_candidate_count": (
                None if index_window is None else index_window.active_candidate_count
            ),
            "completed_candidate_count": (
                None if index_window is None else index_window.completed_candidate_count
            ),
            "repair_recommended": state.repair_recommended,
            "repair_reason": state.repair_reason,
        }
    )
    snapshot_bytes = snapshot_trace_bytes(snapshot)
    if snapshot_bytes is not None:
        extra["snapshot_bytes"] = snapshot_bytes


__all__ = [
    "AgentListingLoadState",
    "listing_trace",
    "listing_snapshot",
    "snapshot_trace_bytes",
]
