"""Rust-backed Focus/fleet count aggregation for fleet-agent projections."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._fleet_agents_payload import count_hosts_from_response


def rust_counts_or_fallback(
    fallback: dict[str, Any],
    *,
    followed_response: Mapping[str, Any] | None,
    fleet_response: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return local plus Rust-projected remote Focus/Fleet running counts."""
    from sase.dispatch.counts import (
        count_focus_and_fleet,
        count_focus_and_fleet_from_federation,
    )

    if _requires_normalized_count(followed_response, fleet_response):
        wire = count_focus_and_fleet(
            {
                "schema_version": 1,
                "local_summaries": [],
                "followed_remote_hosts": [
                    dict(host) for host in count_hosts_from_response(followed_response)
                ],
                "fleet_hosts": [
                    dict(host) for host in count_hosts_from_response(fleet_response)
                ],
            }
        )
    else:
        wire = count_focus_and_fleet_from_federation(
            {
                "schema_version": 1,
                "local_summaries": [],
                "followed_response": (
                    None if followed_response is None else dict(followed_response)
                ),
                "fleet_response": None
                if fleet_response is None
                else dict(fleet_response),
            }
        )

    local = int(fallback.get("local", 0) or 0)
    focus_remote = _nested_count(wire, "focus") or 0
    fleet = _nested_count(wire, "fleet") or 0
    return {
        "local": local,
        "focus_remote": focus_remote,
        "focus_total": local + focus_remote,
        "fleet": fleet,
        "hosts": fallback.get("hosts", 0),
        "wire": wire,
    }


def _requires_normalized_count(
    followed_response: Mapping[str, Any] | None,
    fleet_response: Mapping[str, Any] | None,
) -> bool:
    return _is_normalized(followed_response) or _is_normalized(fleet_response)


def _is_normalized(response: Mapping[str, Any] | None) -> bool:
    return response is not None and "count_hosts" in response


def _nested_count(wire: Mapping[str, Any], key: str) -> int | None:
    section = wire.get(key)
    if not isinstance(section, Mapping):
        return None
    counts = section.get("counts")
    if not isinstance(counts, Mapping):
        return None
    running = counts.get("running")
    return (
        running if isinstance(running, int) and not isinstance(running, bool) else None
    )
