"""Shared builders for project alias service tests."""

from __future__ import annotations

from pathlib import Path

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)


def _record(
    project_name: str,
    *,
    aliases: list[str] | None = None,
    state: str = "enabled",
    system_managed: bool = False,
    launchable: bool | None = None,
    project_file: str | Path | None = None,
    archive_file: str | Path | None = None,
    display_name: str | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=f"/tmp/projects/{project_name}",
        project_file=str(
            project_file or f"/tmp/projects/{project_name}/{project_name}.sase"
        ),
        archive_file=str(archive_file) if archive_file is not None else None,
        workspace_dir=f"/tmp/workspaces/{project_name}",
        state=state,
        state_explicit=False,
        system_managed=system_managed,
        active_claim_count=0,
        launchable=(state == "enabled" if launchable is None else launchable),
        aliases=list(aliases or []),
        warnings=[],
        parse_warnings=[],
        display_name=display_name,
    )
