"""Focus/fleet running-agent count aggregation for fleet-agent projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._fleet_agents_payload import authoritative_running_count, host_payloads


def rust_counts_or_fallback(
    fallback: dict[str, Any],
    *,
    followed_response: Mapping[str, Any] | None,
    fleet_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    counts = dict(fallback)
    fleet_running = authoritative_running_count(fleet_response)
    if fleet_running is not None:
        counts["fleet"] = fleet_running
    focus_running = authoritative_running_count(followed_response)
    if focus_running is not None:
        counts["focus_remote"] = focus_running
        counts["focus_total"] = int(fallback.get("local", 0)) + focus_running
    followed_hosts = host_payloads(followed_response) if followed_response else ()
    fleet_hosts = host_payloads(fleet_response) if fleet_response else ()
    if not followed_hosts and not fleet_hosts:
        return counts
    try:
        from sase.dispatch.counts import count_focus_and_fleet

        wire = count_focus_and_fleet(
            {
                "schema_version": 1,
                "local_summaries": [],
                "followed_remote_hosts": [dict(host) for host in followed_hosts],
                "fleet_hosts": [dict(host) for host in fleet_hosts],
            }
        )
    except Exception:
        return counts

    counts["wire"] = wire
    if focus_running is None:
        rust_focus = _nested_count(wire, "focus")
        if rust_focus is not None:
            counts["focus_remote"] = rust_focus
            counts["focus_total"] = int(fallback.get("local", 0)) + rust_focus
    if fleet_running is None:
        rust_fleet = _nested_count(wire, "fleet")
        if rust_fleet is not None:
            counts["fleet"] = rust_fleet
    return counts


def _nested_count(wire: Mapping[str, Any], key: str) -> int | None:
    section = wire.get(key)
    if not isinstance(section, Mapping):
        return None
    counts = section.get("counts")
    if not isinstance(counts, Mapping):
        return None
    running = counts.get("running")
    return running if isinstance(running, int) else None
