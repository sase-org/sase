"""Restart-safe fair cursors for the ``epic_liveness`` scheduler job."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Callable


STATE_FILENAME = "epic_liveness_cursor.json"
_SCHEMA_VERSION = 1


@dataclass
class EpicLivenessCursor:
    """Remember the next project and last inspected epic in each project."""

    next_project: str | None = None
    candidate_after: dict[str, str] = field(default_factory=dict)


def read_cursor(path: Path) -> EpicLivenessCursor:
    """Read persisted cursor state; malformed state safely starts at the top."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return EpicLivenessCursor()
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
    ):
        return EpicLivenessCursor()
    next_project = payload.get("next_project")
    raw_candidates = payload.get("candidate_after")
    candidate_after = (
        {
            key: value
            for key, value in raw_candidates.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }
        if isinstance(raw_candidates, dict)
        else {}
    )
    return EpicLivenessCursor(
        next_project=next_project if isinstance(next_project, str) else None,
        candidate_after=candidate_after,
    )


def write_cursor(path: Path, cursor: EpicLivenessCursor) -> None:
    """Atomically persist the fairness cursor across job and scheduler restarts."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _SCHEMA_VERSION,
        "next_project": cursor.next_project,
        "candidate_after": dict(sorted(cursor.candidate_after.items())),
    }
    fd, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def rotate_after[T](
    items: list[T], key: str | None, *, item_key: Callable[[T], str]
) -> list[T]:
    """Rotate sorted items to the first key after *key*, wrapping fairly."""

    if not items or not key:
        return items
    for index, item in enumerate(items):
        value = item_key(item)
        if value == key:
            return [*items[index + 1 :], *items[: index + 1]]
        if value > key:
            return [*items[index:], *items[:index]]
    return items


def rotate_to[T](
    items: list[T], key: str | None, *, item_key: Callable[[T], str]
) -> list[T]:
    """Rotate sorted items so *key* is first, or start at its successor key."""

    if not items or not key:
        return items
    for index, item in enumerate(items):
        value = item_key(item)
        if value == key:
            return [*items[index:], *items[:index]]
        if value > key:
            return [*items[index:], *items[:index]]
    return items


__all__ = [
    "EpicLivenessCursor",
    "STATE_FILENAME",
    "read_cursor",
    "rotate_after",
    "rotate_to",
    "write_cursor",
]
