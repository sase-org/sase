"""Append-only comparison of one bead event stream against an ancestor.

This module is pure: it takes two already-parsed event lists and decides
whether the later one is a valid append-only successor, a recoverable
shrink, or a rewrite of published history. Callers in
:mod:`sase.bead._stream_integrity` decide what to do with that verdict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sase.bead._stream_integrity_files import encode_stream_events


@dataclass(frozen=True, slots=True)
class _StreamAnalysis:
    """How one local stream compares to one ancestor version."""

    kind: Literal["ok", "restore_exact", "restore_superset", "rewrite"]
    first_event: int | None = None
    last_event: int | None = None
    restored_events: tuple[dict[str, Any], ...] | None = None
    restored_text: str | None = None
    rewrite_diagnosis: str | None = None


def analyze_stream_against_ancestor(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
    *,
    ancestor_text: str,
    other_streams: dict[str, list[dict[str, Any]]],
    new_stream_ids: set[str],
    stream_id: str,
) -> _StreamAnalysis:
    """Compare *local* to *ancestor* using the Rust append-only rules."""
    rewritten = _first_rewritten_event(ancestor, local)
    if rewritten is not None:
        event_number, ancestor_event, local_event = rewritten
        return _StreamAnalysis(
            kind="rewrite",
            first_event=event_number,
            rewrite_diagnosis=_describe_rewrite(ancestor_event, local_event),
        )

    missing_indexes, extras = _missing_and_extras(ancestor, local)
    if not missing_indexes:
        return _StreamAnalysis(kind="ok")

    missing_events = [ancestor[index] for index in missing_indexes]
    if _relocated_missing_events(
        missing_events,
        other_streams,
        new_stream_ids,
        stream_id,
    ):
        return _StreamAnalysis(kind="ok")

    first_event = missing_indexes[0] + 1
    last_event = missing_indexes[-1] + 1
    if not extras:
        return _StreamAnalysis(
            kind="restore_exact",
            first_event=first_event,
            last_event=last_event,
            restored_events=tuple(ancestor),
            restored_text=ancestor_text,
        )
    restored = list(ancestor)
    restored.extend(extras)
    suffix = encode_stream_events(extras)
    prefix = ancestor_text if ancestor_text.endswith("\n") else ancestor_text + "\n"
    return _StreamAnalysis(
        kind="restore_superset",
        first_event=first_event,
        last_event=last_event,
        restored_events=tuple(restored),
        restored_text=prefix + suffix if ancestor_text else suffix,
    )


def _first_rewritten_event(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> tuple[int, dict[str, Any], dict[str, Any]] | None:
    local_by_id = {
        event_id: event for event in local if (event_id := _event_id(event)) is not None
    }
    for index, event in enumerate(ancestor):
        event_id = _event_id(event)
        if event_id is None:
            continue
        counterpart = local_by_id.get(event_id)
        if counterpart is not None and counterpart != event:
            return index + 1, event, counterpart
    return None


def _describe_rewrite(
    ancestor_event: dict[str, Any],
    local_event: dict[str, Any],
) -> str:
    """Summarize what changed between an ancestor event and its rewrite."""
    added, removed, changed = _diff_paths(ancestor_event, local_event)
    parts: list[str] = []
    if added:
        parts.append(f"added {', '.join(added)}")
    if removed:
        parts.append(f"removed {', '.join(removed)}")
    if changed:
        parts.append(f"value changed at {', '.join(changed)}")
    return "; ".join(parts) if parts else "no field-level difference detected"


def _diff_paths(
    ancestor: Any,
    local: Any,
    prefix: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Return dotted-path (added, removed, changed) keys between two JSON values."""
    if not (isinstance(ancestor, dict) and isinstance(local, dict)):
        return [], [], [prefix or "<root>"]
    added: list[str] = []
    removed: list[str] = []
    changed: list[str] = []
    ancestor_keys = set(ancestor.keys())
    local_keys = set(local.keys())
    for key in sorted(local_keys - ancestor_keys):
        added.append(f"{prefix}.{key}" if prefix else key)
    for key in sorted(ancestor_keys - local_keys):
        removed.append(f"{prefix}.{key}" if prefix else key)
    for key in sorted(ancestor_keys & local_keys):
        if ancestor[key] == local[key]:
            continue
        path = f"{prefix}.{key}" if prefix else key
        sub_added, sub_removed, sub_changed = _diff_paths(
            ancestor[key], local[key], path
        )
        added.extend(sub_added)
        removed.extend(sub_removed)
        changed.extend(sub_changed)
    return added, removed, changed


def _missing_and_extras(
    ancestor: list[dict[str, Any]],
    local: list[dict[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    matched: set[int] = set()
    local_start = 0
    missing: list[int] = []
    for index, ancestor_event in enumerate(ancestor):
        found: int | None = None
        for offset, local_event in enumerate(local[local_start:]):
            if local_event == ancestor_event:
                found = local_start + offset
                break
        if found is None:
            missing.append(index)
            continue
        matched.add(found)
        local_start = found + 1
    extras = [event for offset, event in enumerate(local) if offset not in matched]
    return missing, extras


def _relocated_missing_events(
    missing_events: list[dict[str, Any]],
    other_streams: dict[str, list[dict[str, Any]]],
    new_stream_ids: set[str],
    stream_id: str,
) -> bool:
    if not missing_events or not new_stream_ids:
        return False
    fingerprints: set[tuple[object, ...]] = set()
    event_ids: set[str] = set()
    for candidate_id in new_stream_ids:
        if candidate_id == stream_id:
            continue
        for event in other_streams.get(candidate_id, ()):
            fingerprints.add(_event_fingerprint(event))
            event_id = _event_id(event)
            if event_id is not None:
                event_ids.add(event_id)
    return all(
        _event_id(event) in event_ids or _event_fingerprint(event) in fingerprints
        for event in missing_events
    )


def _event_id(event: dict[str, Any]) -> str | None:
    raw = event.get("event_id")
    return raw if isinstance(raw, str) and raw else None


def _event_fingerprint(event: dict[str, Any]) -> tuple[object, ...]:
    return (
        event.get("timestamp"),
        event.get("actor"),
        event.get("operation"),
    )
