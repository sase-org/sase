"""Machine-local log of agent ``sase bead show`` views.

A view is not a bead event, so it cannot come from the stream reduction in
``sase-core`` and must not be written into the audited artifact-read log,
whose rows require an authored reason and carry link-recording weight.
``sase bead show`` instead appends one small row per shown bead here, only
when an agent identity is present, so interactive use pays nothing and the
audited corpus stays clean. The panel and query layers merge these rows
behind the durable mutation facts as a visibly weaker ``viewed`` signal
that is never promoted to ``read``.

Limitation: this log is machine-local. A remote agent's views are not
visible on this machine while its mutations (which sync through the bead
store) are, so ``viewed`` is always a lower bound.
"""

from __future__ import annotations

import fcntl
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.core.bead_touch_index_facade import BeadTouch, touch_matches_agent
from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.project_aliases import resolve_project_alias_ref

_logger = logging.getLogger(__name__)

BEAD_VIEWS_FILENAME = "bead_views.jsonl"
BEAD_VIEW_LOG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BeadViewEvent:
    """One agent-attributed ``sase bead show`` view of a bead."""

    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    bead_id: str
    agent_name: str


def bead_views_log_path(project: str | None = None, *, cwd: Path | None = None) -> Path:
    """Return ``~/.sase/projects/<key>/bead_views.jsonl``."""

    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / BEAD_VIEWS_FILENAME


def record_bead_show_views(
    bead_ids: Sequence[str],
    *,
    project: str | None = None,
    cwd: Path | None = None,
) -> int:
    """Append one view row per bead id for the acting agent.

    Returns the number of rows written. Writes nothing — not even an empty
    file — when no agent identity is present, so interactive ``sase bead
    show`` use pays nothing. Best-effort and never raises: a failure is
    debug-logged and the show output is unaffected.
    """
    from sase.bead.attribution import acting_agent_name

    try:
        agent_name = acting_agent_name()
        if not agent_name:
            return 0
        cleaned = _clean_bead_ids(bead_ids)
        if not cleaned:
            return 0
        cwd_path = (cwd or Path.cwd()).resolve(strict=False)
        project_name = project or project_memory_name(cwd_path)
        path = bead_views_log_path(project_name)
        timestamp = _event_timestamp(datetime.now(tz=UTC))
        rows = [
            asdict(
                BeadViewEvent(
                    schema_version=BEAD_VIEW_LOG_SCHEMA_VERSION,
                    id=uuid4().hex[:12],
                    timestamp=timestamp,
                    project=project_name,
                    cwd=str(cwd_path),
                    bead_id=bead_id,
                    agent_name=agent_name,
                )
            )
            for bead_id in cleaned
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            with path.open("a", encoding="utf-8") as output_file:
                for row in rows:
                    json.dump(row, output_file, sort_keys=True)
                    output_file.write("\n")
        return len(rows)
    except Exception as exc:
        _logger.debug("Skipping bead view log write: %s", exc)
        return 0


def read_bead_view_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[BeadViewEvent, ...]:
    """Read view events, skipping malformed or wrong-schema JSONL rows."""

    if log_path is None and project is None:
        raise ValueError("project is required when log_path is not provided")
    path = log_path or bead_views_log_path(project)
    try:
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
            if not path.exists():
                return ()
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                return ()
    except OSError:
        return ()

    events: list[BeadViewEvent] = []
    for line in lines:
        if not line.strip():
            continue
        event = _event_from_line(line)
        if event is not None:
            events.append(event)
    return tuple(events)


def views_to_touches(
    events: Sequence[BeadViewEvent],
) -> tuple[BeadTouch, ...]:
    """Fold view events into per-``(agent, bead)`` synthetic touch rows.

    Each row carries only ``verbs={"viewed": n}`` with an empty title, so a
    later merge with durable index rows keeps the durable title and verbs
    and only gains the weaker ``viewed`` count. Rows follow first-seen
    order; callers rank them.
    """

    counts: dict[tuple[str, str], int] = {}
    first_seen: dict[tuple[str, str], str] = {}
    last_seen: dict[tuple[str, str], str] = {}
    first_moment: dict[tuple[str, str], datetime] = {}
    last_moment: dict[tuple[str, str], datetime] = {}
    order: list[tuple[str, str]] = []
    for event in events:
        key = (event.agent_name, event.bead_id)
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
        moment = _parse_moment(event.timestamp)
        if moment is None:
            continue
        if key not in first_moment or moment < first_moment[key]:
            first_moment[key] = moment
            first_seen[key] = event.timestamp
        if key not in last_moment or moment >= last_moment[key]:
            last_moment[key] = moment
            last_seen[key] = event.timestamp
    return tuple(
        BeadTouch(
            actor=agent_name,
            bead_id=bead_id,
            verbs={"viewed": counts[(agent_name, bead_id)]},
            first_at=first_seen.get((agent_name, bead_id), ""),
            last_at=last_seen.get((agent_name, bead_id), ""),
        )
        for agent_name, bead_id in order
    )


def view_touches_for_agent(
    events: Sequence[BeadViewEvent],
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> list[BeadTouch]:
    """Return one agent's synthesized view rows, preserving file order.

    Matching reuses the facade's shared agent matcher, so views attribute
    exactly like durable touches (globalized name, local name, legacy
    bare-local recovery; no prefix or suffix matching).
    """

    return [
        touch
        for touch in views_to_touches(events)
        if touch_matches_agent(
            touch.actor,
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
    ]


def _clean_bead_ids(bead_ids: Sequence[str]) -> list[str]:
    cleaned: list[str] = []
    for bead_id in bead_ids:
        text = (bead_id or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _event_from_line(line: str) -> BeadViewEvent | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _event_from_mapping(data)


def _event_from_mapping(data: Mapping[str, Any]) -> BeadViewEvent | None:
    if data.get("schema_version") != BEAD_VIEW_LOG_SCHEMA_VERSION:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "cwd",
        "bead_id",
        "agent_name",
    )
    if any(not isinstance(data.get(key), str) for key in required_strings):
        return None
    if not data["bead_id"].strip() or not data["agent_name"].strip():
        return None
    return BeadViewEvent(
        schema_version=BEAD_VIEW_LOG_SCHEMA_VERSION,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        bead_id=data["bead_id"],
        agent_name=data["agent_name"],
    )


def _parse_moment(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


__all__ = [
    "BEAD_VIEWS_FILENAME",
    "BEAD_VIEW_LOG_SCHEMA_VERSION",
    "BeadViewEvent",
    "bead_views_log_path",
    "read_bead_view_events",
    "record_bead_show_views",
    "view_touches_for_agent",
    "views_to_touches",
]
