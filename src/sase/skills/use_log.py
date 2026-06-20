"""Foundation helpers for auditable SASE skill-use logging."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.identity import AgentIdentity, discover_agent_runtime
from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.project_aliases import resolve_project_alias_ref

SKILL_USE_LOG_SCHEMA_VERSION = 1


class SkillUseError(ValueError):
    """Base class for skill-use audit validation errors."""


@dataclass(frozen=True)
class SkillUseEvent:
    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    skill_name: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    reason: str
    runtime: str | None


@dataclass(frozen=True)
class SkillUseSkillSummary:
    skill_name: str
    use_count: int
    distinct_agent_count: int
    last_used_at: str
    last_agent: str
    last_reason: str


@dataclass(frozen=True)
class SkillUseAgentSummary:
    agent_name: str
    use_count: int
    distinct_skill_count: int
    last_used_at: str
    last_skill: str
    last_reason: str


@dataclass(frozen=True)
class SkillUseRuntimeSummary:
    runtime: str
    use_count: int
    distinct_skill_count: int
    distinct_agent_count: int
    last_used_at: str
    last_reason: str


def normalize_skill_name(skill_name: str) -> str:
    """Normalize and validate a skill name for audit logging."""
    normalized = skill_name.strip()
    if not normalized:
        raise SkillUseError("skill name must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise SkillUseError("skill name must be a single line")
    return normalized


def normalize_skill_reason(reason: str) -> str:
    """Normalize and validate a skill-use reason for audit logging."""
    normalized = reason.strip()
    if not normalized:
        raise SkillUseError("skill use reason must not be empty")
    return normalized


def build_skill_use_event(
    skill_name: str,
    *,
    reason: str,
    agent: AgentIdentity,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    use_id: str | None = None,
    runtime: str | None = None,
) -> SkillUseEvent:
    """Build a structured log event for an audited skill use."""
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    runtime_value = (
        runtime
        if runtime is not None
        else discover_agent_runtime(artifacts_dir=agent.artifacts_dir)
    )
    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=use_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        skill_name=normalize_skill_name(skill_name),
        agent_name=agent.name,
        agent_source=agent.source,
        artifacts_dir=agent.artifacts_dir,
        reason=normalize_skill_reason(reason),
        runtime=runtime_value,
    )


def skill_use_log_path(project: str | None = None, *, cwd: Path | None = None) -> Path:
    """Return the project-scoped skill-use JSONL path under ``~/.sase``."""
    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "skill_uses.jsonl"


def append_skill_use_event(
    event: SkillUseEvent,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one skill-use event under an exclusive file lock."""
    path = log_path or skill_use_log_path(event.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(asdict(event), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()


def read_skill_use_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[SkillUseEvent, ...]:
    """Read skill-use events, skipping malformed JSONL rows."""
    path = log_path or skill_use_log_path(project)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[SkillUseEvent] = []
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


def filter_skill_use_events(
    events: Iterable[SkillUseEvent],
    *,
    skill_name: str | None = None,
    agent_name: str | None = None,
    runtime: str | None = None,
) -> tuple[SkillUseEvent, ...]:
    """Filter skill-use events by skill name, agent name, and/or runtime."""
    skill_filter = skill_name.strip() if skill_name else None
    agent_filter = agent_name.strip() if agent_name else None
    runtime_filter = runtime.strip() if runtime else None
    return tuple(
        event
        for event in events
        if (skill_filter is None or event.skill_name == skill_filter)
        and (agent_filter is None or event.agent_name == agent_filter)
        and (runtime_filter is None or _runtime_bucket(event.runtime) == runtime_filter)
    )


def summarize_skill_uses_by_skill(
    events: Iterable[SkillUseEvent],
) -> tuple[SkillUseSkillSummary, ...]:
    """Aggregate use counts and latest-use context by skill name."""
    grouped: dict[str, list[SkillUseEvent]] = {}
    for event in events:
        grouped.setdefault(event.skill_name, []).append(event)

    summaries = [
        SkillUseSkillSummary(
            skill_name=skill_name,
            use_count=len(skill_events),
            distinct_agent_count=len({event.agent_name for event in skill_events}),
            last_used_at=_latest_event(skill_events).timestamp,
            last_agent=_latest_event(skill_events).agent_name,
            last_reason=_latest_event(skill_events).reason,
        )
        for skill_name, skill_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.skill_name))


def summarize_skill_uses_by_agent(
    events: Iterable[SkillUseEvent],
) -> tuple[SkillUseAgentSummary, ...]:
    """Aggregate use counts and latest-use context by agent name."""
    grouped: dict[str, list[SkillUseEvent]] = {}
    for event in events:
        grouped.setdefault(event.agent_name, []).append(event)

    summaries = [
        SkillUseAgentSummary(
            agent_name=agent_name,
            use_count=len(agent_events),
            distinct_skill_count=len({event.skill_name for event in agent_events}),
            last_used_at=_latest_event(agent_events).timestamp,
            last_skill=_latest_event(agent_events).skill_name,
            last_reason=_latest_event(agent_events).reason,
        )
        for agent_name, agent_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.agent_name))


def summarize_skill_uses_by_runtime(
    events: Iterable[SkillUseEvent],
) -> tuple[SkillUseRuntimeSummary, ...]:
    """Aggregate use counts and latest-use context by agent runtime."""
    grouped: dict[str, list[SkillUseEvent]] = {}
    for event in events:
        grouped.setdefault(_runtime_bucket(event.runtime), []).append(event)

    summaries = [
        SkillUseRuntimeSummary(
            runtime=runtime,
            use_count=len(runtime_events),
            distinct_skill_count=len({event.skill_name for event in runtime_events}),
            distinct_agent_count=len({event.agent_name for event in runtime_events}),
            last_used_at=_latest_event(runtime_events).timestamp,
            last_reason=_latest_event(runtime_events).reason,
        )
        for runtime, runtime_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.runtime))


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


def _event_from_mapping(data: Mapping[str, Any]) -> SkillUseEvent | None:
    if data.get("schema_version") != SKILL_USE_LOG_SCHEMA_VERSION:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "cwd",
        "skill_name",
        "agent_name",
        "agent_source",
        "reason",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str):
            return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None
    runtime = data.get("runtime")
    if runtime is not None and not isinstance(runtime, str):
        return None

    return SkillUseEvent(
        schema_version=SKILL_USE_LOG_SCHEMA_VERSION,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        skill_name=data["skill_name"],
        agent_name=data["agent_name"],
        agent_source=data["agent_source"],
        artifacts_dir=artifacts_dir,
        reason=data["reason"],
        runtime=runtime,
    )


def _latest_event(events: list[SkillUseEvent]) -> SkillUseEvent:
    return max(events, key=lambda event: event.timestamp)


def _runtime_bucket(runtime: str | None) -> str:
    if runtime is None:
        return "unknown"
    stripped = runtime.strip()
    return stripped or "unknown"


__all__ = [
    "SKILL_USE_LOG_SCHEMA_VERSION",
    "SkillUseAgentSummary",
    "SkillUseError",
    "SkillUseEvent",
    "SkillUseRuntimeSummary",
    "SkillUseSkillSummary",
    "append_skill_use_event",
    "build_skill_use_event",
    "filter_skill_use_events",
    "normalize_skill_name",
    "normalize_skill_reason",
    "read_skill_use_events",
    "skill_use_log_path",
    "summarize_skill_uses_by_agent",
    "summarize_skill_uses_by_runtime",
    "summarize_skill_uses_by_skill",
]
