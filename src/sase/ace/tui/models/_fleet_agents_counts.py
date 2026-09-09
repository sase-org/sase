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
    if followed_response is None and fleet_response is None:
        return counts
    if not _has_worker_payload(followed_response) and not _has_worker_payload(
        fleet_response
    ):
        return counts
    try:
        from sase.dispatch.counts import count_focus_and_fleet_from_federation

        wire = count_focus_and_fleet_from_federation(
            {
                "schema_version": 1,
                "local_summaries": [],
                "followed_response": (
                    dict(followed_response) if followed_response is not None else None
                ),
                "fleet_response": dict(fleet_response)
                if fleet_response is not None
                else None,
            }
        )
    except Exception:
        return counts

    counts["wire"] = wire
    rust_focus = _nested_count(wire, "focus")
    if rust_focus is not None:
        counts["focus_remote"] = rust_focus
        counts["focus_total"] = int(fallback.get("local", 0)) + rust_focus
    rust_fleet = _nested_count(wire, "fleet")
    if rust_fleet is not None:
        counts["fleet"] = rust_fleet
    return counts


def _has_worker_payload(response: Mapping[str, Any] | None) -> bool:
    if response is None:
        return False
    return any(
        isinstance(host.get("payload"), Mapping) for host in host_payloads(response)
    )


def _nested_count(wire: Mapping[str, Any], key: str) -> int | None:
    section = wire.get(key)
    if not isinstance(section, Mapping):
        return None
    counts = section.get("counts")
    if not isinstance(counts, Mapping):
        return None
    running = counts.get("running")
    return running if isinstance(running, int) else None
