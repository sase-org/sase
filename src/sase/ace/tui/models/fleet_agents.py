"""Adapters from federation fleet summaries to Agents-tab rows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sase.dispatch.follow_store import FollowStoreSnapshot

from ._fleet_agents_counts import rust_counts_or_fallback
from ._fleet_agents_follow import active_follow_state, dedupe_rows
from ._fleet_agents_payload import (
    attention_index_by_logical_key,
    catalog_next_cursor,
    catalog_next_cursors_by_host,
    configured_host_count,
    diagnostics_from_attention_response,
    diagnostics_from_response,
    merge_catalog_pages,
    normalize_response,
    response_is_partial,
)
from ._fleet_agents_promotion import followed_batch_family_promotions
from ._fleet_agents_rows import rows_from_response
from .agent import Agent


@dataclass(frozen=True)
class FleetRowsProjection:
    """TUI-ready fleet rows plus safe status metadata."""

    focus_rows: tuple[Agent, ...] = ()
    fleet_rows: tuple[Agent, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    configured_host_count: int = 0
    partial: bool = False
    counts: dict[str, Any] = field(default_factory=dict)


def project_fleet_agents(
    *,
    summary_response: Mapping[str, Any] | None = None,
    catalog_response: Mapping[str, Any] | None = None,
    followed_response: Mapping[str, Any] | None = None,
    attention_response: Mapping[str, Any] | None = None,
    follow_snapshot: FollowStoreSnapshot | None = None,
    local_agent_count: int = 0,
) -> FleetRowsProjection:
    """Project federation responses into remote Agent rows."""
    active_keys, active_locator_ids = active_follow_state(follow_snapshot)
    summary_normalized = normalize_response(summary_response)
    catalog_normalized = normalize_response(catalog_response)
    followed_normalized = normalize_response(followed_response)
    diagnostics = [
        *diagnostics_from_response(summary_normalized),
        *diagnostics_from_response(catalog_normalized),
        *diagnostics_from_response(followed_normalized),
        *diagnostics_from_attention_response(attention_response),
    ]
    attention_by_logical_key = attention_index_by_logical_key(attention_response)
    fleet_source = catalog_normalized or summary_normalized
    fleet_rows = tuple(
        dedupe_rows(
            rows_from_response(
                fleet_source,
                active_keys=active_keys,
                active_locator_ids=active_locator_ids,
                followed_only=False,
                attention_by_logical_key=attention_by_logical_key,
            )
        )
    )
    followed_source = followed_normalized or summary_normalized
    focus_rows = tuple(
        dedupe_rows(
            rows_from_response(
                followed_source,
                active_keys=active_keys,
                active_locator_ids=active_locator_ids,
                followed_only=True,
                attention_by_logical_key=attention_by_logical_key,
            )
        )
    )
    host_count = max(
        configured_host_count(summary_normalized),
        configured_host_count(catalog_normalized),
        configured_host_count(followed_normalized),
    )
    fallback_counts: dict[str, Any] = {
        "local": local_agent_count,
        "focus_remote": len(focus_rows),
        "focus_total": local_agent_count + len(focus_rows),
        "fleet": len(fleet_rows),
        "hosts": host_count,
    }
    fleet_count_source = catalog_response or summary_response
    counts = rust_counts_or_fallback(
        fallback_counts,
        followed_response=followed_response,
        fleet_response=fleet_count_source,
    )
    attention_partial = bool(
        attention_response is not None and attention_response.get("partial")
    )
    return FleetRowsProjection(
        focus_rows=focus_rows,
        fleet_rows=fleet_rows,
        diagnostics=tuple(diagnostics),
        configured_host_count=host_count,
        partial=any(
            response_is_partial(response)
            for response in (
                summary_normalized,
                catalog_normalized,
                followed_normalized,
            )
        )
        or attention_partial,
        counts=counts,
    )


__all__ = [
    "FleetRowsProjection",
    "catalog_next_cursor",
    "catalog_next_cursors_by_host",
    "followed_batch_family_promotions",
    "merge_catalog_pages",
    "project_fleet_agents",
]
