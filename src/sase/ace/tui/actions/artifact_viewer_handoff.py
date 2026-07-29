"""Shared hand-off for opening one path in the terminal artifact viewer."""

from __future__ import annotations

from typing import Any

from ..graphics import (
    ArtifactFileViewSpec,
    is_tmux_session,
    view_artifact_file,
    view_artifact_files_in_tmux_pane,
)
from ..util.external_tool import suspend_for_external_tool


def open_artifact_path(app: Any, path: str) -> None:
    """Open *path* in the rich viewer and surface any best-effort warning."""
    if is_tmux_session():
        result = view_artifact_files_in_tmux_pane((ArtifactFileViewSpec(path),))
        tracker = getattr(app, "_track_artifact_file_tmux_pane", None)
        if result.ok and result.pane_id is not None and callable(tracker):
            tracker(result.pane_id)
    else:
        with suspend_for_external_tool(
            app,
            action="preview_viewer_handoff",
            tool_kind="artifact_file_viewer",
            path_count=1,
            status_message="Opening preview in artifact viewer…",
        ):
            result = view_artifact_file(path)

    if result.warning is not None:
        app.notify(result.warning, severity="warning")


__all__ = ["open_artifact_path"]
