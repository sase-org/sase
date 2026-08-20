"""Audited JSONL helper for ``sase artifact read`` (write path used by CLI)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from sase.agent.identity import AgentIdentity, discover_agent_identity
from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.project_aliases import resolve_project_alias_ref

ARTIFACT_READ_LOG_SCHEMA_VERSION = 1


class ArtifactReadError(ValueError):
    """Raised when an artifact-read audit row cannot be recorded."""


@dataclass(frozen=True)
class ArtifactReadEvent:
    """One audited ``sase artifact read`` invocation."""

    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    ref: str
    reason: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    recorded_link: bool


def _normalize_read_reason(reason: str) -> str:
    """Trim and require a non-empty artifact-read reason."""

    normalized = reason.strip()
    if not normalized:
        raise ArtifactReadError("artifact read reason must not be empty")
    return normalized


def artifact_read_log_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return ``~/.sase/projects/<key>/artifact_reads.jsonl``."""

    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "artifact_reads.jsonl"


def build_artifact_read_event(
    *,
    ref: str,
    reason: str,
    recorded_link: bool,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    read_id: str | None = None,
    agent: AgentIdentity | None = None,
    env: Mapping[str, str] | None = None,
) -> ArtifactReadEvent:
    """Build one attributable artifact-read event.

    Interactive identity is accepted: the JSONL row always stores who read.
    Recording a ``read`` graph edge is a separate, flag-gated decision made
    by the CLI caller.
    """

    import os

    current_env = os.environ if env is None else env
    identity = agent or discover_agent_identity(current_env)
    if identity is None:
        agent_name = _interactive_user(current_env)
        agent_source = "interactive"
        artifacts_dir = _optional_text(current_env.get("SASE_ARTIFACTS_DIR"))
    else:
        agent_name = identity.name
        agent_source = identity.source
        artifacts_dir = identity.artifacts_dir

    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    canonical_ref = ref.strip()
    if not canonical_ref:
        raise ArtifactReadError("artifact read ref must not be empty")
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=read_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        ref=canonical_ref,
        reason=_normalize_read_reason(reason),
        agent_name=agent_name,
        agent_source=agent_source,
        artifacts_dir=artifacts_dir,
        recorded_link=recorded_link,
    )


def append_artifact_read_event(
    event: ArtifactReadEvent,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one artifact-read event under an exclusive file lock.

    Callers must refuse to print the artifact if this write fails, matching
    ``sase glossary read``.
    """

    path = log_path or artifact_read_log_path(event.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            with path.open("a", encoding="utf-8") as output_file:
                json.dump(asdict(event), output_file, sort_keys=True)
                output_file.write("\n")
                output_file.flush()
    except OSError as exc:
        raise ArtifactReadError(
            f"could not record artifact read audit row: {exc}"
        ) from exc


def read_artifact_read_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[ArtifactReadEvent, ...]:
    """Read artifact-read events, skipping malformed or wrong-schema JSONL rows."""

    if log_path is None and project is None:
        raise ValueError("project is required when log_path is not provided")
    path = log_path or artifact_read_log_path(project)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[ArtifactReadEvent] = []
    for line in lines:
        if not line.strip():
            continue
        event = _event_from_line(line)
        if event is not None:
            events.append(event)
    return tuple(events)


def _event_from_line(line: str) -> ArtifactReadEvent | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return _event_from_mapping(data)


def _event_from_mapping(data: Mapping[str, Any]) -> ArtifactReadEvent | None:
    if data.get("schema_version") != ARTIFACT_READ_LOG_SCHEMA_VERSION:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "cwd",
        "ref",
        "reason",
        "agent_name",
        "agent_source",
    )
    if any(not isinstance(data.get(key), str) for key in required_strings):
        return None
    recorded_link = data.get("recorded_link")
    if not isinstance(recorded_link, bool):
        return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None
    return ArtifactReadEvent(
        schema_version=ARTIFACT_READ_LOG_SCHEMA_VERSION,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        ref=data["ref"],
        reason=data["reason"],
        agent_name=data["agent_name"],
        agent_source=data["agent_source"],
        artifacts_dir=artifacts_dir,
        recorded_link=recorded_link,
    )


def _interactive_user(env: Mapping[str, str]) -> str:
    import getpass

    try:
        discovered = _optional_text(getpass.getuser())
    except (KeyError, OSError):
        discovered = None
    return discovered or _optional_text(env.get("USER")) or "unknown"


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


__all__ = [
    "ARTIFACT_READ_LOG_SCHEMA_VERSION",
    "ArtifactReadError",
    "ArtifactReadEvent",
    "append_artifact_read_event",
    "artifact_read_log_path",
    "build_artifact_read_event",
    "read_artifact_read_events",
]
