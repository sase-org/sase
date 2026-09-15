"""Host-level fleet row helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._fleet_agents_payload import host_payloads
from ._fleet_agents_scalars import (
    display_token,
    float_or_none,
    mapping,
    optional_str,
)


@dataclass(frozen=True)
class HostFeedIssue:
    """A remote host whose latest snapshot is invalid or feed-errored.

    Computed independently of :func:`rows_from_response` because an invalid
    host normalizes to zero summaries -- there is no ``Agent`` row left to
    anchor an error state to, so callers that only ever look at rows would
    never learn the host's feed failed at all.
    """

    alias: str
    status: str | None
    error: str | None
    cache_age_seconds: float | None
    diagnostic: str | None


def host_feed_issues(response: Mapping[str, Any] | None) -> tuple[HostFeedIssue, ...]:
    """Return hosts whose latest snapshot reports an invalid or errored feed."""
    if response is None or response.get("disabled"):
        return ()
    issues: list[HostFeedIssue] = []
    for host_index, host in enumerate(host_payloads(response)):
        status = optional_str(host.get("status"))
        freshness_wire = mapping(host.get("freshness"))
        error = optional_str(freshness_wire.get("error"))
        if status != "invalid" and not error:
            continue
        cache_age_seconds = (
            float_or_none(host.get("age_seconds")) if host.get("cached") else None
        )
        issues.append(
            HostFeedIssue(
                alias=host_alias(host, host_index),
                status=status,
                error=error,
                cache_age_seconds=cache_age_seconds,
                diagnostic=host_diagnostic(host, freshness_wire),
            )
        )
    return tuple(issues)


def host_alias(host: Mapping[str, Any], host_index: int) -> str:
    origin = mapping(host.get("origin"))
    alias = optional_str(
        host.get("alias"),
        origin.get("alias"),
        origin.get("name"),
        host.get("installation_id"),
        origin.get("installation_id"),
        host.get("origin_installation_id"),
    )
    if alias:
        return display_token(alias)
    return f"remote-{host_index + 1}"


def host_diagnostic(
    host: Mapping[str, Any],
    freshness_wire: Mapping[str, Any],
) -> str | None:
    diagnostics = host.get("diagnostics")
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if not isinstance(item, Mapping):
                continue
            message = optional_str(item.get("message"), item.get("code"))
            if message:
                return message
    # A rejected envelope (e.g. ``invalid_federation_host``) often carries
    # no per-host diagnostics entry at all -- its only explanation is the
    # freshness error code -- so fall back to that rather than surfacing
    # nothing.
    return optional_str(freshness_wire.get("error"))


_FRESHNESS_RANK: dict[str, int] = {"fresh": 0, "aging": 1, "stale": 2, "unknown": 3}
# The owner's own snapshot-freshness thresholds (sase-core
# FLEET_SNAPSHOT_FRESH_SECONDS / FLEET_SNAPSHOT_STALE_SECONDS) classify how
# old *its* cached copy is. This viewer-side threshold instead classifies
# how old the federation worker's cached response is by the time this
# client polls it. The TUI's own auto-refresh cadence (``refresh_interval``,
# default 10s) is what drives that polling, so a fresh threshold at or below
# it made every steady-state row "aging" the instant a poll landed more than
# 5s after the worker's last fetch -- not a real staleness signal. Sizing it
# above one full poll interval keeps a normally-polled row "fresh".
_FLEET_VIEWER_FRESH_SECONDS = 15.0
_FLEET_VIEWER_STALE_SECONDS = 90.0


def combine_freshness(*values: str | None) -> str | None:
    """Return the least-fresh of the given freshness labels.

    A row must never look fresher than the worst signal available: an
    honestly-stamped owner freshness can still be undercut by a viewer-side
    cache serving an aged copy of that same payload.
    """
    ranked = [value for value in values if value in _FRESHNESS_RANK]
    if not ranked:
        for value in values:
            if value:
                return value
        return None
    return max(ranked, key=lambda value: _FRESHNESS_RANK[value])


def viewer_observed_freshness(host: Mapping[str, Any]) -> str | None:
    """Classify the viewer's own cache age for *host*, or ``None`` when live.

    ``cached`` marks a response the federation worker served from its local
    cache rather than a live fetch; ``age_seconds`` is how long ago that
    cached copy was fetched. A live (non-cached) response carries no viewer
    cache age to fold in.
    """
    if not bool(host.get("cached")):
        return None
    age_seconds = float_or_none(host.get("age_seconds"))
    from sase.dispatch.counts import classify_cache_freshness

    decision = classify_cache_freshness(
        {
            "schema_version": 1,
            "viewer_monotonic_elapsed_seconds": age_seconds,
            "fresh_threshold_seconds": _FLEET_VIEWER_FRESH_SECONDS,
            "stale_threshold_seconds": _FLEET_VIEWER_STALE_SECONDS,
        }
    )
    return optional_str(decision.get("freshness"))
