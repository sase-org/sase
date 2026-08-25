"""Read-only compatibility for legacy ``sase glossary read`` audit events."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.memory.web.resolution import normalize_glossary_reference
from sase.project_aliases import resolve_project_alias_ref

GLOSSARY_READ_LOG_SCHEMA_VERSION = 1


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


def normalize_read_reason(reason: str) -> str:
    """Normalize and validate a legacy glossary-read reason."""
    normalized = reason.strip()
    if not normalized:
        raise ValueError("glossary read reason must not be empty")
    return normalized


def glossary_read_log_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped legacy glossary-read JSONL path under ``~/.sase``."""
    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "glossary_reads.jsonl"


def read_glossary_read_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[GlossaryReadEvent, ...]:
    """Read legacy glossary-read events, skipping malformed JSONL rows."""
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


__all__ = [
    "GLOSSARY_READ_LOG_SCHEMA_VERSION",
    "GlossaryReadEvent",
    "filter_glossary_read_events",
    "glossary_read_log_path",
    "normalize_read_reason",
    "read_glossary_read_events",
]
