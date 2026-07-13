"""Shared helpers for ace Projects pane tests."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from sase.ace.tui.modals.projects_pane import ProjectsPane
from sase.core.project_lifecycle_wire import ProjectRecordWire


class ProjectsPaneTestApp(App[None]):
    """Minimal host that mounts a :class:`ProjectsPane` and focuses its list.

    The Projects pane is a widget, not a screen, so tests mount it here the
    way :class:`ConfigCenterModal` does and rely on ``focus_default()`` to
    focus the option list (browse-first), matching the real Admin Center so
    the pane's own key bindings fire exactly as they do in production.
    """

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, projects_root: Path | None = None) -> None:
        super().__init__()
        self._projects_root = projects_root

    def compose(self) -> ComposeResult:
        yield ProjectsPane(projects_root=self._projects_root, id="projects")

    def on_mount(self) -> None:
        self.query_one("#projects", ProjectsPane).focus_default()


def make_project_record(
    name: str,
    *,
    state: str = "enabled",
    explicit: bool = True,
    claims: int = 0,
    launchable: bool = True,
    warnings: list[str] | None = None,
    aliases: list[str] | None = None,
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
        aliases=aliases or [],
        warnings=warnings or [],
        parse_warnings=[],
    )
