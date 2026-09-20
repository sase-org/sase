"""Structured Agents refresh cost and fallback trace helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, get_args

from ...util.trace import is_enabled, trace_event

AgentRefreshDataCost = Literal[
    "tier2_full_history",
    "tier1_broad_load",
    "artifact_delta_load",
]

AgentRefreshDisplayCost = Literal[
    "display_full_rebuild",
    "display_panel_rebuild",
    "display_panel_insert",
    "display_panel_remove",
    "display_row_insert",
    "row_patch",
    "row_remove",
]

AgentRefreshFallbackReason = Literal[
    "missing_launch_result",
    "missing_artifact_dir",
    "delta_read_failure",
    "active_search",
    "search_query_changed",
    "unsupported_grouping",
    "stale_grouping_mode",
    "status_membership_change",
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
        "display_panel_insert",
        "display_panel_remove",
        "display_row_insert",
        "row_patch",
        "row_remove",
    }
)

ALL_AGENT_REFRESH_FALLBACK_REASONS: frozenset[AgentRefreshFallbackReason] = frozenset(
    {
        "missing_launch_result",
        "missing_artifact_dir",
        "delta_read_failure",
        "active_search",
        "search_query_changed",
        "unsupported_grouping",
        "stale_grouping_mode",
        "status_membership_change",
        "width_growth",
        "panel_membership_change",
        "workflow_tree_change",
        "clan_member_order_change",
        "dirty_queue_overflow",
        "unknown_watcher_path",
        "persistence_error",
    }
)


# ``AgentRefreshDisplayCost`` is declared most-expensive first.
_DISPLAY_COST_ORDER: tuple[AgentRefreshDisplayCost, ...] = get_args(
    AgentRefreshDisplayCost
)

_PAINT_LOG_ATTR = "_agents_paint_log"
_PENDING_OUTCOME_ATTR = "_agents_pending_display_outcome"


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
    # Widget id of the one panel a partial rebuild is attributed to; ``None`` for
    # a record that concerns the whole tab.
    panel: str | None = None


@dataclass
class _PendingDisplayOutcome:
    """Costliest display cost and first fallback since the last paint frame.

    Constant-size on purpose: runtime ticks record ``row_patch`` costs while no
    frame is being taken, so anything that grew per record would leak.
    """

    cost: AgentRefreshDisplayCost | None = None
    fallback_reason: str | None = None


def paint_log_collector(app: object) -> list[Any] | None:
    """Return the list ``app`` collects paint frames into (tests), if any."""

    collector = getattr(app, _PAINT_LOG_ATTR, None)
    return collector if isinstance(collector, list) else None


def paint_log_active(app: object) -> bool:
    """Return whether paint frames are collected (test list or trace flag)."""

    return paint_log_collector(app) is not None or is_enabled()


def _note_display_outcome(
    app: object,
    display_cost: AgentRefreshDisplayCost,
    fallback_reason: str | None,
) -> None:
    pending = getattr(app, _PENDING_OUTCOME_ATTR, None)
    if pending is None:
        pending = _PendingDisplayOutcome()
        setattr(app, _PENDING_OUTCOME_ATTR, pending)
    if pending.cost is None or _DISPLAY_COST_ORDER.index(
        display_cost
    ) < _DISPLAY_COST_ORDER.index(pending.cost):
        pending.cost = display_cost
    if pending.fallback_reason is None:
        pending.fallback_reason = fallback_reason


def take_display_outcome(
    app: object,
) -> tuple[AgentRefreshDisplayCost | None, str | None]:
    """Return and clear the costliest display cost and first fallback reason."""

    pending = getattr(app, _PENDING_OUTCOME_ATTR, None)
    if pending is None:
        return None, None
    setattr(app, _PENDING_OUTCOME_ATTR, None)
    return pending.cost, pending.fallback_reason


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
    panel: str | None = None,
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
        panel=panel,
    )
    record_fields = {
        key: value for key, value in asdict(record).items() if value is not None
    }
    record_fields.update(fields)
    trace_event("agents.refresh_work", **record_fields)

    collector = getattr(app, "_agents_refresh_trace_records", None)
    if isinstance(collector, list):
        collector.append(record)
    if display_cost is not None and paint_log_active(app):
        _note_display_outcome(app, display_cost, fallback_reason)
    return record
