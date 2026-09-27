"""Remote-fleet projection fields for the Agents tab model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentStateFleetFields:
    """Display/runtime-only remote-fleet state for one agent row."""

    # Remote fleet projection metadata. These fields are display/runtime-only:
    # local mutating actions must treat rows with a fleet origin as read-only.
    fleet_origin_alias: str | None = field(default=None, compare=False)
    fleet_origin_installation_id: str | None = field(default=None, compare=False)
    fleet_logical_locator: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_exact_locator: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_logical_key: str | None = field(default=None, compare=False)
    fleet_exact_key: str | None = field(default=None, compare=False)
    fleet_revision: int | None = field(default=None, compare=False)
    fleet_row_revision: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_freshness: str | None = field(default=None, compare=False)
    fleet_connection_health: str | None = field(default=None, compare=False)
    fleet_observed_at_unix: float | None = field(default=None, compare=False)
    # Raw host-envelope status ("ok"/"invalid") and freshness error code
    # (e.g. "invalid_envelope"), distinct from the per-row
    # ``fleet_connection_health`` vocabulary above. Every row from the same
    # host carries the same values, so any row can anchor a host-level
    # error surface even when the host's own count fields are unset.
    fleet_host_status: str | None = field(default=None, compare=False)
    fleet_host_feed_error: str | None = field(default=None, compare=False)
    fleet_host_cache_age_seconds: float | None = field(default=None, compare=False)
    # Authoritative counts for this row's origin host, sourced from the
    # host's own `authoritative_counts` envelope rather than a client-side
    # recount of loaded rows. Every row from the same host carries the same
    # pair, so a group banner can read either member row for host totals.
    fleet_host_running_count: int | None = field(default=None, compare=False)
    fleet_host_total_count: int | None = field(default=None, compare=False)
    fleet_host_waiting_count: int | None = field(default=None, compare=False)
    fleet_host_failed_count: int | None = field(default=None, compare=False)
    fleet_host_done_count: int | None = field(default=None, compare=False)
    fleet_host_unknown_count: int | None = field(default=None, compare=False)
    fleet_capabilities: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_content: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_followed: bool = field(default=False, compare=False)
    fleet_bounded_intent: str | None = field(default=None, compare=False)
    fleet_diagnostic: str | None = field(default=None, compare=False)
    # Source-controller provisional launch metadata. These fields are present
    # only for rows inserted while a `%dispatch` launch is settling; real fleet
    # catalog rows replace them once the owner reports the launched agent.
    fleet_dispatch_operation_key: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_dispatch_status: str | None = field(default=None, compare=False)
    fleet_dispatch_message: str | None = field(default=None, compare=False)
    fleet_dispatch_prompt: str | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    fleet_dispatch_payload: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    # A pending remote question/gate entry for this row (see
    # `sase_core.fleet_attention`'s `FleetAttentionEntryWire`), or None when
    # no attention is currently pending. Answering never mutates this field
    # directly; a fresh fleet refresh replaces it once the owner settles it.
    fleet_attention: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    # Structural fleet-wire facts consumed by remote node synthesis. These
    # are display/runtime-only and never drive local membership policy.
    fleet_row_kind: str | None = field(default=None, compare=False)
    fleet_current_instance: bool = field(default=False, compare=False)
    fleet_container_projected_concrete_agent: bool = field(
        default=False,
        compare=False,
    )

    # Internal source marker for dismissed bundles loaded only for revive.
    _loaded_from_dismissed_bundle: bool = field(
        default=False, compare=False, repr=False
    )

    # On-disk path of the dismissed bundle file this agent was loaded from.
    # Populated alongside ``_loaded_from_dismissed_bundle`` by the dismissed
    # bundle loader so the revive audit log can record which file was deleted.
    _dismissed_bundle_path: str | None = field(default=None, compare=False, repr=False)
