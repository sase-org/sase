"""Shared helpers for ace project management modal tests."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.core.project_lifecycle_wire import ProjectRecordWire


class ProjectManagementTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def make_project_record(
    name: str,
    *,
    state: str = "active",
    explicit: bool = True,
    claims: int = 0,
    launchable: bool = True,
    warnings: list[str] | None = None,
    system_managed: bool = False,
    project_dir: str | None = None,
    project_file: str | None = None,
) -> ProjectRecordWire:
    project_dir_text = project_dir or f"/tmp/projects/{name}"
    project_file_text = project_file or f"{project_dir_text}/{name}.sase"
    return ProjectRecordWire(
        schema_version=1,
        project_name=name,
        project_dir=project_dir_text,
        project_file=project_file_text,
        archive_file=None,
        workspace_dir=f"/tmp/workspaces/{name}",
        state=state,
        state_explicit=explicit,
        system_managed=system_managed,
        active_claim_count=claims,
        launchable=launchable,
        warnings=warnings or [],
        parse_warnings=[],
    )
