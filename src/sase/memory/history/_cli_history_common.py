"""Shared helpers for the split ``cli_history`` command modules.

Public helpers live here because more than one new ``cli_history_*`` module
needs them. Single-use helpers stay private inside their sole consumer.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from rich.console import Console

from sase.memory.history.scopes import HistoryScopeError
from sase.memory.history.service import HistoryNotFoundError, HistoryService


def parse_date_bound(value: str, *, end_of_day: bool) -> int:
    """Parse a ``YYYY-MM-DD`` (or full ISO) date to epoch seconds."""
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise HistoryScopeError(f"invalid date {value!r}: expected YYYY-MM-DD") from exc
    if len(value) == 10 and end_of_day:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return int(parsed.timestamp())


def emit_json(console: Console, payload: Any) -> None:
    """Print a wire payload as deterministic JSON."""
    console.print_json(json.dumps(payload, sort_keys=True))


def at_to_version(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    at: str,
    *,
    include_hidden: bool,
) -> tuple[str, str | None]:
    """Translate ``-A/--at`` to a core version selector plus notice.

    Ordinals (``7``/``v7``), ``~N``, SHA prefixes, ``blob:OID``, and
    ``now`` pass through. Dates select the latest version at or before
    that day. A ``blob:OID`` selector (a full blob OID or a unique
    prefix of at least 7 hex characters) resolves through the timeline
    to the newest committed version with that blob, so it reads the
    same on wheels before and after the core ``blob:`` selector.
    """
    if at == "now" or at.startswith("~") or at.startswith("v") or at.isdigit():
        return at, None
    if len(at) >= 5 and at[:5].lower() == "blob:":
        return _blob_to_version(service, scope, core_selector, at)
    # A bare date is YYYY-MM-DD; anything else goes to core as a SHA prefix.
    if len(at) == 10 and at[4] == "-" and at[7] == "-":
        bound = parse_date_bound(at, end_of_day=True)
        timeline = service.timeline(scope, core_selector, include_hidden=True)
        versions = [
            v
            for v in timeline.get("versions", ())
            if int(v.get("ordinal", 0) or 0) > 0
            and int(v.get("committer_time", 0) or 0) <= bound
        ]
        if not versions:
            raise HistoryNotFoundError(
                f"no version of {core_selector!r} at or before {at}"
            )
        newest = max(versions, key=lambda v: int(v.get("ordinal", 0)))
        return f"v{newest.get('ordinal')}", (
            f"{core_selector} at {at} is v{newest.get('ordinal')}"
        )
    return at, None


def _blob_to_version(
    service: HistoryService,
    scope: Any,
    core_selector: str,
    at: str,
) -> tuple[str, str | None]:
    """Resolve ``blob:OID`` through the timeline to newest ``vN``."""
    raw = at[5:]
    if len(raw) < 7 or any(ch not in "0123456789abcdefABCDEF" for ch in raw):
        raise HistoryScopeError(f"invalid version selector: {at}")
    ordinal = blob_ordinal_from_timeline(
        service.timeline(scope, core_selector, include_hidden=True), raw
    )
    if ordinal is None:
        raise HistoryNotFoundError(f"no version {at} for subject {core_selector!r}")
    if ordinal == -1:
        raise HistoryScopeError(
            f"ambiguous blob prefix {at} for subject {core_selector!r}"
        )
    return f"v{ordinal}", f"{core_selector} at {at} is v{ordinal}"


def blob_ordinal_from_timeline(timeline: dict[str, Any], raw_oid: str) -> int | None:
    """Return the newest committed ordinal matching a blob OID prefix.

    ``raw_oid`` is the hex after ``blob:`` (at least 7 characters).
    Deleted rows never match. Returns the newest ordinal, ``None`` when
    nothing matches, or ``-1`` when the prefix is ambiguous across
    distinct blobs.
    """
    lowered = raw_oid.lower()
    newest = 0
    distinct: set[str] = set()
    for row in timeline.get("versions", ()):
        if not isinstance(row, dict):
            continue
        try:
            ordinal = int(row.get("ordinal", 0) or 0)
        except (TypeError, ValueError):
            continue
        if ordinal <= 0:
            continue
        if str(row.get("kind", "") or "").lower() == "deleted":
            continue
        blob = row.get("blob_oid")
        if not isinstance(blob, str) or not blob:
            continue
        if not blob.lower().startswith(lowered):
            continue
        distinct.add(blob.lower())
        if ordinal > newest:
            newest = ordinal
    if newest == 0:
        return None
    if len(distinct) > 1:
        return -1
    return newest


__all__ = [
    "at_to_version",
    "blob_ordinal_from_timeline",
    "emit_json",
    "parse_date_bound",
]
