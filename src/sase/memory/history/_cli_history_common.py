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

    Ordinals (``7``/``v7``), ``~N``, SHA prefixes, and ``now`` pass
    through. Dates select the latest version at or before that day.
    """
    if at == "now" or at.startswith("~") or at.startswith("v") or at.isdigit():
        return at, None
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


__all__ = ["at_to_version", "emit_json", "parse_date_bound"]
