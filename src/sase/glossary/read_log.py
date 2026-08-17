"""Foundation helpers for auditable ``sase glossary read`` access."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.identity import AgentIdentity
from sase.agent.identity import (
    require_agent_identity as _require_agent_identity,
)
from sase.core.paths import sase_projects_dir
from sase.glossary.resolution import normalize_glossary_reference
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.project_aliases import resolve_project_alias_ref

GLOSSARY_READ_LOG_SCHEMA_VERSION = 1


class GlossaryReadError(ValueError):
    """Base class for glossary-read validation errors."""


@dataclass(frozen=True)
class GlossaryReadEvent:
    """One audited glossary-read invocation."""

    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    reason: str
    terms: tuple[str, ...]
    related_terms: tuple[str, ...]
    depth_limit: int | None
    definition_bytes: int
    source_path: str | None


@dataclass(frozen=True)
class GlossaryReadTermSummary:
    """Aggregated read counts and latest-read context for one glossary term."""

    term: str
    read_count: int
    distinct_agent_count: int
    last_read_at: str
    last_agent: str
    last_reason: str


@dataclass(frozen=True)
class GlossaryReadAgentSummary:
    """Aggregated read counts and latest-read context for one agent."""

    agent_name: str
    read_count: int
    distinct_term_count: int
    last_read_at: str
    last_term: str
    last_reason: str


def require_agent_identity(env: Mapping[str, str] | None = None) -> AgentIdentity:
    """Return the current agent identity or raise a clear auditability error."""
    return _require_agent_identity(env, purpose="glossary reads")


def normalize_read_reason(reason: str) -> str:
    """Normalize and validate a glossary-read reason for audit logging."""
    normalized = reason.strip()
    if not normalized:
        raise GlossaryReadError("glossary read reason must not be empty")
    return normalized


def build_glossary_read_event(
    *,
    reason: str,
    agent: AgentIdentity,
    terms: Sequence[str],
    related_terms: Sequence[str] = (),
    depth_limit: int | None = None,
    definition_bytes: int = 0,
    source_path: str | None = None,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    read_id: str | None = None,
) -> GlossaryReadEvent:
    """Build a structured log event for a resolved glossary read."""
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    return GlossaryReadEvent(
        schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
        id=read_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        agent_name=agent.name,
        agent_source=agent.source,
        artifacts_dir=agent.artifacts_dir,
        reason=normalize_read_reason(reason),
        terms=tuple(terms),
        related_terms=tuple(related_terms),
        depth_limit=depth_limit,
        definition_bytes=definition_bytes,
        source_path=source_path,
    )


def glossary_read_log_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped glossary-read JSONL path under ``~/.sase``."""
    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "glossary_reads.jsonl"


def append_glossary_read_event(
    event: GlossaryReadEvent,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one glossary-read event under an exclusive file lock."""
    path = log_path or glossary_read_log_path(event.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(asdict(event), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()


def read_glossary_read_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[GlossaryReadEvent, ...]:
    """Read glossary-read events, skipping malformed or wrong-schema JSONL rows."""
    path = log_path or glossary_read_log_path(project)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[GlossaryReadEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        event = _event_from_mapping(data)
        if event is not None:
            events.append(event)
    return tuple(events)


def filter_glossary_read_events(
    events: Iterable[GlossaryReadEvent],
    *,
    term: str | None = None,
    agent_name: str | None = None,
) -> tuple[GlossaryReadEvent, ...]:
    """Filter read events by normalized term and/or agent name."""
    term_filter = normalize_glossary_reference(term) if term else ""
    agent_filter = agent_name.strip() if agent_name else None
    return tuple(
        event
        for event in events
        if (not term_filter or _event_has_term(event, term_filter))
        and (agent_filter is None or event.agent_name == agent_filter)
    )


def summarize_glossary_reads_by_term(
    events: Iterable[GlossaryReadEvent],
) -> tuple[GlossaryReadTermSummary, ...]:
    """Aggregate read counts and latest-read context by canonical glossary term."""
    grouped: dict[str, list[GlossaryReadEvent]] = {}
    for event in events:
        for event_term in _event_terms(event):
            grouped.setdefault(event_term, []).append(event)

    summaries = [
        GlossaryReadTermSummary(
            term=event_term,
            read_count=len(term_events),
            distinct_agent_count=len({item.agent_name for item in term_events}),
            last_read_at=_latest_event(term_events).timestamp,
            last_agent=_latest_event(term_events).agent_name,
            last_reason=_latest_event(term_events).reason,
        )
        for event_term, term_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.term))


def summarize_glossary_reads_by_agent(
    events: Iterable[GlossaryReadEvent],
) -> tuple[GlossaryReadAgentSummary, ...]:
    """Aggregate read counts and latest-read context by agent name."""
    grouped: dict[str, list[GlossaryReadEvent]] = {}
    for event in events:
        grouped.setdefault(event.agent_name, []).append(event)

    summaries = [
        GlossaryReadAgentSummary(
            agent_name=agent,
            read_count=len(agent_events),
            distinct_term_count=len(
                {term for item in agent_events for term in _event_terms(item)}
            ),
            last_read_at=_latest_event(agent_events).timestamp,
            last_term=_first_requested_term(_latest_event(agent_events)),
            last_reason=_latest_event(agent_events).reason,
        )
        for agent, agent_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.agent_name))


def _event_has_term(event: GlossaryReadEvent, needle: str) -> bool:
    return any(
        normalize_glossary_reference(item) == needle for item in _event_terms(event)
    )


def _event_terms(event: GlossaryReadEvent) -> tuple[str, ...]:
    seen: set[str] = set()
    terms: list[str] = []
    for item in (*event.terms, *event.related_terms):
        if item in seen:
            continue
        seen.add(item)
        terms.append(item)
    return tuple(terms)


def _first_requested_term(event: GlossaryReadEvent) -> str:
    return event.terms[0] if event.terms else ""


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


def _event_from_mapping(data: Mapping[str, Any]) -> GlossaryReadEvent | None:
    if data.get("schema_version") != GLOSSARY_READ_LOG_SCHEMA_VERSION:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "cwd",
        "agent_name",
        "agent_source",
        "reason",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str):
            return None
    terms = _string_tuple(data.get("terms"))
    related_terms = _string_tuple(data.get("related_terms"))
    if terms is None or related_terms is None:
        return None
    if not isinstance(data.get("definition_bytes"), int):
        return None
    depth_limit = data.get("depth_limit")
    if depth_limit is not None and not isinstance(depth_limit, int):
        return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None
    source_path = data.get("source_path")
    if source_path is not None and not isinstance(source_path, str):
        return None

    return GlossaryReadEvent(
        schema_version=GLOSSARY_READ_LOG_SCHEMA_VERSION,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        agent_name=data["agent_name"],
        agent_source=data["agent_source"],
        artifacts_dir=artifacts_dir,
        reason=data["reason"],
        terms=terms,
        related_terms=related_terms,
        depth_limit=depth_limit,
        definition_bytes=data["definition_bytes"],
        source_path=source_path,
    )


def _string_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list | tuple):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _latest_event(events: list[GlossaryReadEvent]) -> GlossaryReadEvent:
    return max(events, key=lambda event: event.timestamp)


__all__ = [
    "GLOSSARY_READ_LOG_SCHEMA_VERSION",
    "GlossaryReadAgentSummary",
    "GlossaryReadError",
    "GlossaryReadEvent",
    "GlossaryReadTermSummary",
    "append_glossary_read_event",
    "build_glossary_read_event",
    "filter_glossary_read_events",
    "glossary_read_log_path",
    "normalize_read_reason",
    "read_glossary_read_events",
    "require_agent_identity",
    "summarize_glossary_reads_by_agent",
    "summarize_glossary_reads_by_term",
]
