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
    configured_host_count,
    diagnostics_from_response,
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
    """Project federation responses into Focus and Fleet Agent rows."""
    active_keys, active_locator_ids = active_follow_state(follow_snapshot)
    diagnostics = [
        *diagnostics_from_response(summary_response),
        *diagnostics_from_response(catalog_response),
        *diagnostics_from_response(followed_response),
        *diagnostics_from_response(attention_response),
    ]
    attention_by_logical_key = attention_index_by_logical_key(attention_response)
    fleet_source = catalog_response or summary_response
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
    followed_source = followed_response or summary_response
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
        configured_host_count(summary_response),
        configured_host_count(catalog_response),
        configured_host_count(followed_response),
    )
    fallback_counts: dict[str, Any] = {
        "local": local_agent_count,
        "focus_remote": len(focus_rows),
        "focus_total": local_agent_count + len(focus_rows),
        "fleet": len(fleet_rows),
        "hosts": host_count,
    }
    counts = rust_counts_or_fallback(
        fallback_counts,
        followed_response=followed_response,
        fleet_response=fleet_source,
    )
    return FleetRowsProjection(
        focus_rows=focus_rows,
        fleet_rows=fleet_rows,
        diagnostics=tuple(diagnostics),
        configured_host_count=host_count,
        partial=any(
            bool(response and response.get("partial"))
            for response in (
                summary_response,
                catalog_response,
                followed_response,
                attention_response,
            )
        ),
        counts=counts,
    )


def followed_logical_locators(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[dict[str, Any], ...]:
    """Return active logical locators for a followed-batch request."""
    if snapshot is None:
        return ()
    locators: list[dict[str, Any]] = []
    for record in snapshot.active_records:
        locator = record.get("logical_locator")
        if isinstance(locator, Mapping):
            locators.append(dict(locator))
    return tuple(locators)


def followed_logical_keys(
    snapshot: FollowStoreSnapshot | None,
) -> tuple[str, ...]:
    """Return active logical keys for a bounded attention read."""
    if snapshot is None:
        return ()
    keys: list[str] = []
    for record in snapshot.active_records:
        key = record.get("logical_key")
        if isinstance(key, str) and key:
            keys.append(key)
    return tuple(keys)


__all__ = [
    "FleetRowsProjection",
    "followed_batch_family_promotions",
    "followed_logical_keys",
    "followed_logical_locators",
    "project_fleet_agents",
]
