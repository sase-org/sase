"""Image attachment inference helpers for agent artifact loaders."""

from __future__ import annotations

import os
from pathlib import Path

from sase.axe.image_attachments import collect_saved_diff_image_paths

from ..agent import Agent


def append_inferred_diff_images(agent: Agent) -> None:
    """Append existing image files referenced by an agent's saved diff."""
    workspace_dir = _resolve_workspace_dir(agent.project_file, agent.workspace_num)
    if workspace_dir is None:
        return
    images = collect_saved_diff_image_paths(
        workspace_dir,
        agent.diff_path,
        existing_files=agent.extra_files,
    )
    if images:
        agent.extra_files = [*agent.extra_files, *images]


def _resolve_workspace_dir(project_file: str, workspace_num: int | None) -> str | None:
    if workspace_num is None or workspace_num <= 0:
        return None

    from sase.workspace_provider import detect_workflow_type, get_workspace_directory
    from sase.workspace_provider.utils import parse_workspace_dir

    try:
        workflow_type = detect_workflow_type(project_file)
        primary_dir = parse_workspace_dir(project_file) or ""
        project_name = Path(project_file).parent.name
        workspace_dir = get_workspace_directory(
            workflow_type,
            workspace_num,
            project_name,
            primary_dir,
        ).rstrip("/")
    except Exception:
        return None

    if os.path.isdir(workspace_dir):
        return workspace_dir
    return None
