"""Read-only touch-index queries and agent matching.

The reduction itself lives in ``sase-core`` (``bead/touch_index.rs``); this
module owns the thin query binding wrapper with wire-to-dataclass
conversion, the agent-identity matching from the epic plan (so the CLI, the
panel, and any later caller share one matcher), and the durable-behind-views
merge order for the machine-local view log. Public names are re-exported
through :mod:`sase.core.bead_touch_index_facade`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
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


TOUCH_MEMBER_QUERY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TouchQueryMember:
    """One exact agent-identity selector in priority order."""

    globalized_name: str
    local_name: str | None = None


@dataclass(frozen=True)
class TouchSourceIdentity:
    """Identity of the source file a targeted touch query actually read."""

    missing: bool
    size: int
    mtime_ns: int
    dev: int
    ino: int


@dataclass(frozen=True)
class TouchMemberRow:
    """One claimed touch row plus the ordinal of the claiming member."""

    member_index: int
    touch: BeadTouch


def _require_member_query_schema() -> None:
    binding = require_rust_binding("bead_touch_member_query_wire_schema_version")
    version = int(binding())
    if version != TOUCH_MEMBER_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs touch member query wire is stale: "
            f"expected {TOUCH_MEMBER_QUERY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _member_payload(
    members: Sequence[TouchQueryMember | Mapping[str, Any]],
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for member in members:
        if isinstance(member, Mapping):
            globalized = member.get("globalized_name")
            local = member.get("local_name")
        else:
            globalized = member.globalized_name
            local = member.local_name
        payload.append(
            {
                "globalized_name": str(globalized or ""),
                "local_name": None if local is None else str(local),
            }
        )
    return payload


def _owner_payload(identity: Any | None) -> dict[str, Any] | None:
    from sase.core.agent_identity_facade import AgentIdentitySnapshot

    snapshot = identity if identity is not None else AgentIdentitySnapshot.current()
    owner = getattr(snapshot, "owner", None)
    if owner is None:
        return None
    return {
        "username": str(getattr(owner, "username", "")),
        "machine_name": str(getattr(owner, "machine_name", "")),
    }


def _roots_payload(identity: Any | None) -> list[str]:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        known_owner_roots,
    )

    snapshot = identity if identity is not None else AgentIdentitySnapshot.current()
    try:
        roots = known_owner_roots(snapshot)
    except Exception:
        return []
    return [str(root) for root in roots]


def _request_payload(
    members: Sequence[TouchQueryMember | Mapping[str, Any]],
    identity: Any | None,
) -> dict[str, Any]:
    return {
        "members": _member_payload(members),
        "owner": _owner_payload(identity),
        "known_owner_roots": _roots_payload(identity),
    }


def _source_identity_from_wire(raw: object, *, what: str) -> TouchSourceIdentity:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            f"sase_core_rs returned an incompatible {what} source identity: "
            "expected an object"
        )
    missing = raw.get("missing", False)
    if not isinstance(missing, bool):
        raise RuntimeError(
            f"sase_core_rs returned an incompatible {what} source identity: "
            "missing must be a boolean"
        )
    return TouchSourceIdentity(
        missing=missing,
        size=_require_identity_int(raw, "size", what),
        mtime_ns=_require_identity_int(raw, "mtime_ns", what),
        dev=_require_identity_int(raw, "dev", what),
        ino=_require_identity_int(raw, "ino", what),
    )


def _require_identity_int(raw: Mapping[str, Any], field: str, what: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            f"sase_core_rs returned an incompatible {what} source identity: "
            f"{field} must be a non-negative integer"
        )
    return value


def _member_rows_from_wire(
    raw: object, *, member_count: int, what: str
) -> list[TouchMemberRow]:
    if not isinstance(raw, list):
        raise RuntimeError(
            f"sase_core_rs returned an incompatible {what} result: "
            "expected rows to be a list"
        )
    rows: list[TouchMemberRow] = []
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, Mapping):
            raise RuntimeError(
                f"sase_core_rs returned an incompatible {what} row "
                f"{position}: expected an object"
            )
        member_index = item.get("member_index")
        if (
            not isinstance(member_index, int)
            or isinstance(member_index, bool)
            or member_index < 0
            or member_index >= member_count
        ):
            raise RuntimeError(
                f"sase_core_rs returned an incompatible {what} row "
                f"{position}: member_index out of range"
            )
        raw_touch = item.get("touch")
        if not isinstance(raw_touch, Mapping):
            raise RuntimeError(
                f"sase_core_rs returned an incompatible {what} row "
                f"{position}: touch must be an object"
            )
        rows.append(
            TouchMemberRow(
                member_index=member_index,
                touch=_touch_from_dict(raw_touch),
            )
        )
    return rows


def query_touch_index_members(
    index_path: Path | str,
    members: Sequence[TouchQueryMember | Mapping[str, Any]],
    identity: Any | None = None,
) -> tuple[list[TouchMemberRow], TouchSourceIdentity, str, int]:
    """Return the indexed touches claimed by ordered *members*.

    Only matching rows are constructed: unrelated actors are dropped inside
    the Rust query, so a large index costs one scan, not a full Python
    snapshot. A missing, truncated, unparseable, or wrong-schema index is a
    cache miss that returns no rows with an empty generation, never an
    error. Returns ``(rows, source, generation, schema_version)``; rows
    arrive newest touch first, then by bead id and actor, like the
    unfiltered query.
    """
    _require_member_query_schema()
    request = _request_payload(members, identity)
    binding = require_rust_binding("bead_touch_member_query")
    payload = binding(str(index_path), request)
    if not isinstance(payload, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible touch member query "
            "result: expected an object"
        )
    rows = _member_rows_from_wire(
        payload.get("rows"), member_count=len(request["members"]), what="touch"
    )
    source = _source_identity_from_wire(payload.get("source"), what="touch")
    return (
        rows,
        source,
        str(payload.get("generation", "")),
        int(payload.get("schema_version", 0)),
    )


def query_bead_view_members(
    views_path: Path | str,
    members: Sequence[TouchQueryMember | Mapping[str, Any]],
    identity: Any | None = None,
) -> tuple[list[TouchMemberRow], TouchSourceIdentity, bool]:
    """Return the folded viewed rows claimed by ordered *members*.

    Streams the legacy views log and folds only claimed events, so unrelated
    agents' views are released as the log is scanned instead of retained as
    a whole-project snapshot. Malformed single lines are skipped. Returns
    ``(rows, source, complete)``; rows arrive in first-seen order and the
    caller merges them behind durable index rows. ``complete`` is false when
    an I/O error cut the scan short: discard such an answer and treat the
    query as a miss, never publish it.
    """
    _require_member_query_schema()
    request = _request_payload(members, identity)
    binding = require_rust_binding("bead_view_member_query")
    payload = binding(str(views_path), request)
    if not isinstance(payload, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible bead view member query "
            "result: expected an object"
        )
    rows = _member_rows_from_wire(
        payload.get("rows"), member_count=len(request["members"]), what="view"
    )
    source = _source_identity_from_wire(payload.get("source"), what="view")
    complete = payload.get("complete", False)
    if complete is not True:
        return [], source, False
    return rows, source, True


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

    Only the agent's rows are constructed: the ordered single-member query
    applies the shared matcher (exact globalized and local spellings plus
    legacy bare-local-name recovery) inside the Rust core. A cache miss
    returns an empty query, never an error.
    """
    rows, _source, generation, schema_version = query_touch_index_members(
        index_path,
        [TouchQueryMember(globalized_name, local_name)],
        identity,
    )
    return BeadTouchQuery(
        schema_version=schema_version,
        generation=generation,
        touches=tuple(row.touch for row in rows),
    )


__all__ = [
    "TOUCH_MEMBER_QUERY_WIRE_SCHEMA_VERSION",
    "TouchMemberRow",
    "TouchQueryMember",
    "TouchSourceIdentity",
    "merge_view_touches",
    "query_bead_view_members",
    "query_touches_for_agent",
    "query_touch_index_members",
    "touch_matches_agent",
]
