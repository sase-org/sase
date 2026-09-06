"""Preserve byte-identical raw event dicts across a semantic stream merge."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.core.bead_conflict_facade import merge_event_streams_with_relocation

from .conflict_resolver_streams import empty_stream


def streams_in_raw_event_preference_order(
    *,
    base: dict[str, Any],
    upstream: dict[str, Any],
    upstream_stage: int,
    local: dict[str, Any],
    local_stage: int,
) -> tuple[dict[str, Any], ...]:
    stages = {1: base, upstream_stage: upstream, local_stage: local}
    # Stage 2 is "ours", the current HEAD whose ancestor bytes the
    # append-only guard compares against after the resolver writes the merge.
    return tuple(stages[stage] for stage in (2, 3, 1) if stage in stages)


def raw_event_candidates_by_id(
    streams: Iterable[dict[str, Any]],
) -> dict[str, tuple[dict[str, Any], ...]]:
    candidates: dict[str, list[dict[str, Any]]] = {}
    for stream in streams:
        events = stream.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            if isinstance(event_id, str):
                candidates.setdefault(event_id, []).append(event)
    return {event_id: tuple(events) for event_id, events in candidates.items()}


def with_raw_equivalent_events(
    stream: dict[str, Any],
    raw_events_by_id: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any]:
    events = stream.get("events")
    if not isinstance(events, list):
        return stream

    stream_id = str(stream["stream_id"])
    preserved: list[Any] = []
    changed = False
    for event in events:
        raw_event = _raw_equivalent_event(event, stream_id, raw_events_by_id)
        if raw_event is None:
            preserved.append(event)
            continue
        preserved.append(raw_event)
        changed = changed or raw_event is not event
    if not changed:
        return stream
    updated = dict(stream)
    updated["events"] = preserved
    return updated


def _raw_equivalent_event(
    merged_event: Any,
    stream_id: str,
    raw_events_by_id: dict[str, tuple[dict[str, Any], ...]],
) -> dict[str, Any] | None:
    if not isinstance(merged_event, dict):
        return None
    event_id = merged_event.get("event_id")
    if not isinstance(event_id, str):
        return None
    for raw_event in raw_events_by_id.get(event_id, ()):
        if _normalized_raw_event(raw_event, stream_id) == merged_event:
            return raw_event
    return None


def _normalized_raw_event(
    event: dict[str, Any], stream_id: str
) -> dict[str, Any] | None:
    stream = {
        "stream_id": stream_id,
        "root_issue_id": stream_id,
        "events": [event],
    }
    try:
        outcome = merge_event_streams_with_relocation(
            empty_stream(stream_id),
            stream,
            stream,
            None,
        )
    except Exception:
        return None
    events = outcome.get("merged", {}).get("events", [])
    if len(events) != 1 or not isinstance(events[0], dict):
        return None
    return events[0]
