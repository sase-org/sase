"""Content refresh, extraction, and editor actions for the zoom panel modal."""

from __future__ import annotations

import os
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.core.paths import get_sase_tmpdir

from ..actions.clipboard import copy_to_system_clipboard
from ..widgets.prompt_panel import AgentPromptPanel
from ..widgets.renderable_text import renderable_to_text
from .zoom_panel_rendering import ACTIVE_STATUSES
from .zoom_panel_types import ZoomPanelTarget
from .zoom_panel_widgets import ZoomFilePanel, ZoomToolsPanel

if TYPE_CHECKING:
    from ..models import Agent


def seed_panels(modal: Any) -> None:
    """Paint base-panel renderables immediately to avoid an empty first frame."""
    if modal._content_seeded:
        return
    modal._content_seeded = True
    if modal._seed.metadata_renderable:
        modal.query_one("#zoom-metadata-panel", AgentPromptPanel).update(
            modal._seed.metadata_renderable
        )
    modal.query_one("#zoom-metadata-scroll", VerticalScroll).border_subtitle = (
        modal._seed.metadata_subtitle or ""
    )
    file_panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
    if modal._seed.file_renderable:
        file_panel.update(modal._seed.file_renderable)
    modal.query_one("#zoom-file-scroll", VerticalScroll).border_subtitle = (
        modal._seed.file_subtitle or ""
    )
    file_panel._current_agent = modal._last_agent
    if modal._seed.file_list:
        file_panel._file_list = list(modal._seed.file_list)
        file_panel._current_file_index = min(
            max(modal._seed.file_index, 0),
            len(modal._seed.file_list) - 1,
        )
        file_panel.freeze_current_list()
    tools_panel = modal.query_one("#zoom-tools-panel", ZoomToolsPanel)
    tools_panel.set_detail_level(
        modal._seed.tools_detail_level,
        rerender=False,
    )
    if modal._seed.tools_renderable:
        tools_panel.update(modal._seed.tools_renderable)
    modal.query_one("#zoom-tools-scroll", VerticalScroll).border_subtitle = (
        modal._seed.tools_subtitle or ""
    )


def refresh_active_panel(modal: Any, *, force: bool) -> None:
    agent = modal._agent_provider()
    if agent is None:
        modal._update_header()
        return
    modal._last_agent = agent
    if modal._target == ZoomPanelTarget.METADATA:
        refresh_metadata(modal, agent)
    elif modal._target == ZoomPanelTarget.FILE:
        refresh_file(modal, agent, force=force)
    else:
        refresh_tools(modal, agent, force=force)
    modal._update_header()


def refresh_metadata(modal: Any, agent: Agent) -> None:
    panel = modal.query_one("#zoom-metadata-panel", AgentPromptPanel)
    panel.attempt_view_mode = modal._seed.attempt_view_mode
    panel.attempt_pinned_number = modal._seed.attempt_number
    modal._metadata_generation += 1
    generation = modal._metadata_generation

    def is_current(
        agent_identity: tuple[Any, ...],
        worker_generation: int,
        attempt_view_mode: str,
        attempt_pinned_number: int | None,
    ) -> bool:
        current = modal._agent_provider()
        return (
            current is not None
            and current.identity == agent_identity
            and modal._metadata_generation == worker_generation
            and modal._seed.attempt_view_mode == attempt_view_mode
            and modal._seed.attempt_number == attempt_pinned_number
            and modal._target == ZoomPanelTarget.METADATA
        )

    if (
        modal._seed.attempt_number is None
        and agent.agent_type.value == "workflow"
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    ):
        panel.start_workflow_detail_render(
            agent,
            generation=generation,
            attempt_view_mode=modal._seed.attempt_view_mode,
            attempt_pinned_number=modal._seed.attempt_number,
            is_current=is_current,
        )
        return
    set_render_context = getattr(panel, "set_agent_detail_render_context", None)
    if callable(set_render_context):
        set_render_context(
            generation=generation,
            attempt_view_mode=modal._seed.attempt_view_mode,
            attempt_pinned_number=modal._seed.attempt_number,
            is_current=is_current,
        )
    panel.update_display(agent)


def refresh_file(modal: Any, agent: Agent, *, force: bool) -> None:
    panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
    if modal._seed.attempt_number is not None:
        panel.show_empty()
        modal._has_file_content = False
        modal._show_target(ZoomPanelTarget.METADATA)
        return

    if force:
        current_path = panel.get_current_file_path()
        if current_path is not None:
            panel.display_static_file(current_path)
        else:
            panel.refresh_file(agent)
        return

    files = agent.all_files
    if agent.status not in ACTIVE_STATUSES and files:
        start_index = min(max(panel.current_file_index, 0), len(files) - 1)
        if panel.current_file_count == 0 and modal._seed.file_list:
            start_index = min(max(modal._seed.file_index, 0), len(files) - 1)
        panel.set_file_list(files, start_index=start_index)
    else:
        panel.update_display(agent, stale_threshold_seconds=modal._refresh_interval)
    panel.freeze_current_list()


def refresh_tools(modal: Any, agent: Agent, *, force: bool) -> None:
    panel = modal.query_one("#zoom-tools-panel", ZoomToolsPanel)
    if force:
        panel.refresh_tools(agent)
    else:
        panel.update_display(agent, stale_threshold_seconds=modal._refresh_interval)


def zoom_text(modal: Any) -> str | None:
    file_path: str | None = None
    if modal._target == ZoomPanelTarget.FILE:
        file_panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
        content = file_panel.get_current_content()
        if content:
            return content
        file_path = file_panel.get_current_file_path()
    elif modal._target == ZoomPanelTarget.TOOLS:
        content = modal.query_one("#zoom-tools-panel", ZoomToolsPanel).get_tools_text()
        if content:
            return content
    active_panel = modal.query_one(f"#zoom-{modal._target.value}-panel", Static)
    rendered_text = renderable_to_text(getattr(active_panel, "content", None))
    return rendered_text or file_path


def editor_info(modal: Any) -> tuple[str | None, str | None, str]:
    if modal._target == ZoomPanelTarget.FILE:
        panel = modal.query_one("#zoom-file-panel", ZoomFilePanel)
        return panel.get_current_file_path(), panel.get_current_content(), ".diff"
    if modal._target == ZoomPanelTarget.TOOLS:
        return (
            None,
            modal.query_one("#zoom-tools-panel", ZoomToolsPanel).get_tools_text(),
            ".md",
        )
    return (None, modal._zoom_text(), ".md")


def open_in_editor(
    modal: Any, file_path: str | None, content: str | None, suffix: str
) -> None:
    editor = os.environ.get("EDITOR") or "nvim"
    if file_path is not None:
        with modal.app.suspend():
            subprocess.run([editor, os.path.expanduser(file_path)], check=False)
        return
    if content is None:
        modal.notify("No content to edit", severity="warning")
        return
    fd, tmp_path = tempfile.mkstemp(
        suffix=suffix,
        prefix="sase_ace_zoom_",
        dir=get_sase_tmpdir(),
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        with modal.app.suspend():
            subprocess.run([editor, tmp_path], check=False)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def action_edit_zoom_content(modal: Any) -> None:
    open_in_editor(modal, *editor_info(modal))


def action_copy_zoom_content(modal: Any) -> None:
    content = zoom_text(modal)
    if not content:
        modal.notify("No content to copy", severity="warning")
        return
    line_count = content.count("\n") + (1 if not content.endswith("\n") else 0)
    if copy_to_system_clipboard(content):
        modal.notify(f"Copied: zoom content ({line_count} lines)")
    else:
        modal.notify("Copy failed - clipboard tool not available", severity="error")


def action_refresh_zoom_content(modal: Any) -> None:
    refresh_active_panel(modal, force=True)
