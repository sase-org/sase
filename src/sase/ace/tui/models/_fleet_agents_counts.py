"""Focus/fleet running-agent count aggregation for fleet-agent projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._fleet_agents_payload import host_payloads


def rust_counts_or_fallback(
    fallback: dict[str, Any],
    *,
    followed_response: Mapping[str, Any] | None,
    fleet_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    followed_hosts = host_payloads(followed_response) if followed_response else ()
    fleet_hosts = host_payloads(fleet_response) if fleet_response else ()
    if not followed_hosts and not fleet_hosts:
        return fallback
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
        return fallback

    counts = dict(fallback)
    counts["wire"] = wire
    focus_running = _nested_count(wire, "focus")
    fleet_running = _nested_count(wire, "fleet")
    if focus_running is not None:
        counts["focus_remote"] = focus_running
        counts["focus_total"] = int(fallback.get("local", 0)) + focus_running
    if fleet_running is not None:
        counts["fleet"] = fleet_running
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
