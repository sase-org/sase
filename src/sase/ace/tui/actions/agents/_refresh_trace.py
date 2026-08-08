"""Structured Agents refresh cost and fallback trace helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from ...util.trace import trace_event

AgentRefreshDataCost = Literal[
    "tier2_full_history",
    "tier1_broad_load",
    "artifact_delta_load",
]

AgentRefreshDisplayCost = Literal[
    "display_full_rebuild",
    "display_panel_rebuild",
    "row_patch",
    "row_remove",
    "row_insert",
]

AgentRefreshFallbackReason = Literal[
    "missing_launch_result",
    "missing_artifact_dir",
    "delta_read_failure",
    "active_search",
    "unsupported_grouping",
    "stale_grouping_mode",
    "width_growth",
    "panel_membership_change",
    "workflow_tree_change",
    "clan_member_order_change",
    "dirty_queue_overflow",
    "unknown_watcher_path",
    "persistence_error",
]

ALL_AGENT_REFRESH_DATA_COSTS: frozenset[AgentRefreshDataCost] = frozenset(
    {
        "tier2_full_history",
        "tier1_broad_load",
        "artifact_delta_load",
    }
)

ALL_AGENT_REFRESH_DISPLAY_COSTS: frozenset[AgentRefreshDisplayCost] = frozenset(
    {
        "display_full_rebuild",
        "display_panel_rebuild",
        "row_patch",
        "row_remove",
        "row_insert",
    }
)

ALL_AGENT_REFRESH_FALLBACK_REASONS: frozenset[AgentRefreshFallbackReason] = frozenset(
    {
        "missing_launch_result",
        "missing_artifact_dir",
        "delta_read_failure",
        "active_search",
        "unsupported_grouping",
        "stale_grouping_mode",
        "width_growth",
        "panel_membership_change",
        "workflow_tree_change",
        "clan_member_order_change",
        "dirty_queue_overflow",
        "unknown_watcher_path",
        "persistence_error",
    }
)


@dataclass(frozen=True)
class _AgentRefreshTraceRecord:
    """One structured trace point for Agents refresh work.

    Test fakes can expose ``_agents_refresh_trace_records`` as a list to
    collect these records without reading log text or JSONL output.
    """

    stage: str
    source: str
    data_cost: AgentRefreshDataCost | None = None
    display_cost: AgentRefreshDisplayCost | None = None
    fallback_reason: str | None = None
    full_history: bool | None = None


def normalize_refresh_source(source: str | None) -> str:
    """Return the canonical refresh source label used in trace records."""

    return source or "unknown"


def classify_agents_data_cost(
    *,
    full_history: bool = False,
    load_state: Any | None = None,
    artifact_delta: bool = False,
) -> AgentRefreshDataCost:
    """Classify the data-read cost independently from display cost."""

    if artifact_delta:
        return "artifact_delta_load"
    if full_history:
        return "tier2_full_history"
    if load_state is not None:
        tier = getattr(load_state, "tier", None)
        complete_history = bool(getattr(load_state, "complete_history", False))
        if tier == "tier2" or complete_history:
            return "tier2_full_history"
    return "tier1_broad_load"


def infer_broad_load_fallback_reason(
    *,
    source: str,
    full_history_reason: str | None = None,
) -> str | None:
    """Infer the named fallback that currently routes through a broad load."""

    if full_history_reason:
        return full_history_reason
    if source == "launch":
        return "missing_launch_result"
    if source == "auto_refresh":
        return "unknown_watcher_path"
    if source.endswith("_error_recovery"):
        return "persistence_error"
    return None


def record_agents_refresh_trace(
    app: object,
    *,
    stage: str,
    source: str | None,
    data_cost: AgentRefreshDataCost | None = None,
    display_cost: AgentRefreshDisplayCost | None = None,
    fallback_reason: str | None = None,
    full_history: bool | None = None,
    **fields: Any,
) -> _AgentRefreshTraceRecord:
    """Emit one structured trace point and optionally append it to ``app``."""

    record = _AgentRefreshTraceRecord(
        stage=stage,
        source=normalize_refresh_source(source),
        data_cost=data_cost,
        display_cost=display_cost,
        fallback_reason=fallback_reason,
        full_history=full_history,
    )
    record_fields = {
        key: value for key, value in asdict(record).items() if value is not None
    }
    record_fields.update(fields)
    trace_event("agents.refresh_work", **record_fields)

    collector = getattr(app, "_agents_refresh_trace_records", None)
    if isinstance(collector, list):
        collector.append(record)
    return record
