"""Read-only touch-index queries and agent matching.

The reduction itself lives in ``sase-core`` (``bead/touch_index.rs``); this
module owns the thin query binding wrapper with wire-to-dataclass
conversion, the agent-identity matching from the epic plan (so the CLI, the
panel, and any later caller share one matcher), and the durable-behind-views
merge order for the machine-local view log. Public names are re-exported
through :mod:`sase.core.bead_touch_index_facade`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.bead_touch_index_models import (
    BeadNotePreview,
    BeadTouch,
    BeadTouchClose,
    BeadTouchQuery,
)
from sase.core.rust import require_rust_binding


def query_touch_index(
    index_path: Path | str, actors: list[str] | tuple[str, ...] | None = None
) -> BeadTouchQuery:
    """Return the indexed touches, optionally restricted to *actors*.

    Read-only: loads the index file only, never scans or parses streams. A
    missing, truncated, unparseable, or wrong-schema index is a cache miss
    that returns no rows, never an error. ``actors=None`` returns every
    actor's touches so the facade can apply the legacy bare-local-name match
    itself.
    """
    binding = require_rust_binding("bead_touch_index_query")
    payload: Mapping[str, Any] = binding(
        str(index_path), None if actors is None else list(actors)
    )
    touches = payload.get("touches") or ()
    return BeadTouchQuery(
        schema_version=int(payload.get("schema_version", 0)),
        generation=str(payload.get("generation", "")),
        touches=tuple(
            _touch_from_dict(row) for row in touches if isinstance(row, dict)
        ),
    )


def _touch_from_dict(payload: Mapping[str, Any]) -> BeadTouch:
    verbs_raw = payload.get("verbs")
    verbs: dict[str, int] = {}
    if isinstance(verbs_raw, Mapping):
        for verb, count in verbs_raw.items():
            try:
                total = int(count)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if total > 0:
                verbs[str(verb)] = total
    current_note_count = _positive_int(payload.get("current_note_count"))
    note_preview = _note_preview_from_dict(payload.get("note_preview"))
    creation_reason = _optional_reason_text(payload.get("creation_reason"))
    if current_note_count == 0:
        # A preview without its required current-note count is malformed.  Do
        # not let an incomplete newer wire produce a blank or misattributed UI
        # block on an otherwise usable older index.
        note_preview = None
    return BeadTouch(
        actor=str(payload.get("actor", "")),
        bead_id=str(payload.get("bead_id", "")),
        title=str(payload.get("title", "")),
        issue_type=str(payload.get("issue_type", "")),
        status=str(payload.get("status", "")),
        verbs=verbs,
        first_at=str(payload.get("first_at", "")),
        last_at=str(payload.get("last_at", "")),
        current_note_count=current_note_count,
        note_preview=note_preview,
        close=_close_from_dict(payload.get("close")),
        creation_reason=creation_reason,
        creation_reason_truncated=payload.get("creation_reason_truncated") is True,
    )


def _optional_reason_text(value: object) -> str:
    """Return a trimmed reason string, or ``""`` for missing/non-string wire."""
    if not isinstance(value, str):
        return ""
    return value.strip()


def _positive_int(value: object) -> int:
    """Return a non-negative integer wire value, rejecting bools and junk."""
    if isinstance(value, bool):
        return 0
    if not isinstance(value, int | float | str):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


def _note_preview_from_dict(value: object) -> BeadNotePreview | None:
    """Convert an additive schema-2 preview, or safely reject malformed data."""
    if not isinstance(value, Mapping):
        return None
    note_id = value.get("id")
    author = value.get("author")
    timestamp = value.get("timestamp")
    text = value.get("text")
    if not all(
        isinstance(field, str) and field.strip()
        for field in (note_id, author, timestamp, text)
    ):
        return None
    assert isinstance(note_id, str)
    assert isinstance(author, str)
    assert isinstance(timestamp, str)
    assert isinstance(text, str)
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None

    def optional_text(key: str) -> str | None:
        candidate = value.get(key)
        return (
            candidate.strip()
            if isinstance(candidate, str) and candidate.strip()
            else None
        )

    return BeadNotePreview(
        id=note_id.strip(),
        author=author.strip(),
        timestamp=timestamp,
        text=text,
        edited_at=optional_text("edited_at"),
        edited_by=optional_text("edited_by"),
        truncated=value.get("truncated") is True,
    )


def _close_from_dict(value: object) -> BeadTouchClose | None:
    """Convert an additive close record, or safely reject malformed data."""
    if not isinstance(value, Mapping):
        return None
    closed_at = value.get("closed_at")
    if not isinstance(closed_at, str) or not closed_at.strip():
        return None
    resolution_raw = value.get("resolution")
    resolution = (
        resolution_raw.strip()
        if isinstance(resolution_raw, str) and resolution_raw.strip()
        else "done"
    )
    reason_raw = value.get("reason")
    reason = reason_raw.strip() if isinstance(reason_raw, str) else ""
    return BeadTouchClose(
        closed_at=closed_at.strip(),
        resolution=resolution,
        reason=reason,
        standing=value.get("standing") is True,
    )


def touch_matches_agent(
    actor: str,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> bool:
    """Return whether an index touch *actor* is one agent's work.

    The touch matches when its actor, after trimming, equals the agent's
    globalized name or local ``agent_name``, or when
    :func:`globalize_owned_agent_name` maps the recorded actor onto the
    agent's globalized name (which recovers the legacy bare-local-name rows).
    Matching is exact after those normalizations: no prefix or suffix
    matching, because bead ids and agent names both use dotted suffixes and a
    loose match would cross-attribute. Anything unrecognizable (an email
    address, a name validation rejects) never matches.
    """
    candidate = actor.strip()
    if not candidate:
        return False
    if candidate == globalized_name:
        return True
    if local_name is not None and candidate == local_name:
        return True
    try:
        from sase.core.agent_identity_facade import globalize_owned_agent_name

        if identity is None:
            from sase.core.agent_identity_facade import AgentIdentitySnapshot

            identity = AgentIdentitySnapshot.current()
        return globalize_owned_agent_name(candidate, identity) == globalized_name
    except Exception:
        return False


def _touches_for_agent(
    touches: Any,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> list[BeadTouch]:
    """Filter touch rows down to one agent's work, preserving order."""
    return [
        touch
        for touch in touches
        if touch_matches_agent(
            touch.actor,
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
    ]


def merge_view_touches(
    durable_touches: Any,
    view_touches: Any,
) -> tuple[BeadTouch, ...]:
    """Concatenate durable index rows with synthesized view rows.

    Durable rows stay first so a later per-bead merge keeps the durable
    title and verbs and only gains the weaker ``viewed`` count. View rows
    (from the machine-local ``bead_views.jsonl`` log) never override
    durable facts; a bead with only views still surfaces as a
    ``viewed``-only entry. Both inputs may be any sequence and are never
    mutated.
    """
    return tuple(durable_touches) + tuple(view_touches)


def query_touches_for_agent(
    index_path: Path | str,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> BeadTouchQuery:
    """Query the index and return one agent's touches, newest first.

    Loads every actor's touches (``actors=None``) so the legacy
    bare-local-name match applies, then filters to the agent. A cache miss
    returns an empty query, never an error.
    """
    query = query_touch_index(index_path)
    return BeadTouchQuery(
        schema_version=query.schema_version,
        generation=query.generation,
        touches=tuple(
            _touches_for_agent(
                query.touches,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            )
        ),
    )


__all__ = [
    "merge_view_touches",
    "query_touches_for_agent",
    "query_touch_index",
    "touch_matches_agent",
]
