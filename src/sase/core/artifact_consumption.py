"""Durable write-side ledger for artifact-reference consumption."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import json
import os
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sase.agent.identity import AgentIdentity, resolve_audit_identity
from sase.core.artifact_file_helpers import artifact_file_mime_type
from sase.core.artifact_file_types import (
    artifact_file_association_from_dir,
    default_artifact_files_root,
)
from sase.memory.locks import locked_file


ARTIFACT_CONSUMPTION_LOG_SCHEMA_VERSION = 1

ArtifactConsumptionRole = Literal["source", "report", "image", "test-result"]
ArtifactConsumptionResolutionStatus = Literal["exact", "drifted", "vcs_backed"]


@dataclass(frozen=True)
class ArtifactConsumptionEvent:
    """One successful artifact-reference expansion."""

    id: str
    timestamp: str
    ref: str
    ref_kind: str
    fragment: str | None
    role: ArtifactConsumptionRole
    artifact_id: str | None
    resolved_path: str | None
    resolution_status: ArtifactConsumptionResolutionStatus
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    project: str | None


def default_artifact_consumption_log_path() -> Path:
    """Return the append-only artifact-consumption ledger path."""

    return default_artifact_files_root() / "consumption.jsonl"


def artifact_consumption_role(
    kind_type: str,
    kind: str,
    resolved_path: Path | str | None,
) -> ArtifactConsumptionRole:
    """Derive the v1 consumption role without artifact-index I/O."""

    if kind_type in {"chat", "document"}:
        return "report"
    if kind_type != "file" or resolved_path is None:
        return "source"

    mime_type = artifact_file_mime_type(resolved_path)
    if mime_type.startswith(("image/", "video/")):
        return "image"
    if mime_type in {"application/pdf", "text/markdown", "text/plain"}:
        return "report"
    return "source"


def build_artifact_consumption_event(
    *,
    ref: str,
    ref_kind: str,
    fragment: str | None,
    role: ArtifactConsumptionRole,
    artifact_id: str | None,
    resolved_path: Path | str | None,
    resolution_status: ArtifactConsumptionResolutionStatus,
    now: datetime | None = None,
    consumption_id: str | None = None,
    env: Mapping[str, str] | None = None,
    agent: AgentIdentity | None = None,
    login_user: str | None = None,
) -> ArtifactConsumptionEvent:
    """Build an attributable consumption event."""

    current_env = os.environ if env is None else env
    identity = agent or resolve_audit_identity(current_env, login_user=login_user)

    project = None
    if identity.artifacts_dir is not None:
        project = artifact_file_association_from_dir(
            identity.artifacts_dir,
            agent_name=identity.name,
        ).project

    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    return ArtifactConsumptionEvent(
        id=consumption_id or uuid4().hex[:12],
        timestamp=timestamp,
        ref=ref,
        ref_kind=ref_kind,
        fragment=fragment,
        role=role,
        artifact_id=artifact_id,
        resolved_path=None if resolved_path is None else str(resolved_path),
        resolution_status=resolution_status,
        agent_name=identity.name,
        agent_source=identity.source,
        artifacts_dir=identity.artifacts_dir,
        project=project,
    )


def append_artifact_consumption_events(
    events: Iterable[ArtifactConsumptionEvent],
    *,
    log_path: Path | None = None,
) -> None:
    """Append a batch of events under one exclusive file lock."""

    batch = tuple(events)
    if not batch:
        return

    path = log_path or default_artifact_consumption_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            for event in batch:
                json.dump(
                    {
                        "schema_version": ARTIFACT_CONSUMPTION_LOG_SCHEMA_VERSION,
                        "consumption": asdict(event),
                    },
                    output_file,
                    sort_keys=True,
                )
                output_file.write("\n")
            output_file.flush()


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


__all__ = [
    "ARTIFACT_CONSUMPTION_LOG_SCHEMA_VERSION",
    "ArtifactConsumptionEvent",
    "ArtifactConsumptionResolutionStatus",
    "ArtifactConsumptionRole",
    "append_artifact_consumption_events",
    "artifact_consumption_role",
    "build_artifact_consumption_event",
    "default_artifact_consumption_log_path",
]
