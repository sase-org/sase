"""Shared public helpers for the agent publication outbox doctor test modules."""

from __future__ import annotations

import json
from pathlib import Path

from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.doctor.runner import DoctorContext

__all__ = ["doctor_context", "make_item", "make_record", "write_outbox"]


def doctor_context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(
        cwd=tmp_path,
        project=None,
        sase_home=tmp_path / ".sase",
    )


def make_record(tmp_path: Path, *, name: str = "alpha") -> ProjectRecordWire:
    project_dir = tmp_path / ".sase" / "projects" / name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(tmp_path / name),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
    )


def make_item(
    *,
    project_key: str = "alpha",
    local_agent: str = "foo--code",
    revision: str = "a" * 40,
    attempts: int = 0,
    last_error: str | None = None,
    quarantined: bool = False,
    terminal: bool = False,
    terminal_reason: str | None = None,
    created_at: float = 100.0,
    updated_at: float = 100.0,
) -> dict[str, object]:
    hood = local_agent.split("--", 1)[0]
    return AgentPublicationOutboxItem(
        project_key=project_key,
        project="Alpha",
        local_agent=local_agent,
        global_agent=f"alice.athena.{local_agent}",
        primary_revision=revision,
        local_hood=hood,
        attempts=attempts,
        last_error=last_error,
        quarantined=quarantined,
        quarantined_at=updated_at if quarantined else None,
        terminal=terminal,
        terminal_reason=terminal_reason,
        created_at=created_at,
        updated_at=updated_at,
    ).to_json_dict()


def write_outbox(
    root: Path,
    project_key: str,
    rows: list[dict[str, object]],
    *,
    schema_version: int = 2,
) -> Path:
    path = root / "projects" / project_key / "agents-publication-outbox.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"schema_version": schema_version, "items": rows}),
        encoding="utf-8",
    )
    return path
