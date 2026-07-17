"""Shared tmux helpers for terminal artifact viewer launches."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence

from ._viewer_types import (
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    viewer_result_from_warnings,
)

_ARTIFACT_FILE_NOTIFY_PID_ENV = "SASE_ARTIFACT_FILE_NOTIFY_PID"
_ARTIFACT_RETURN_PANE_ID_ENV = "SASE_ARTIFACT_RETURN_PANE_ID"


def is_tmux_session() -> bool:
    """Return whether the current process is running inside tmux."""

    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


def tmux_warning_result(
    code: str,
    message: str,
    *,
    tool: str | None = "tmux",
) -> ArtifactFileViewerResult:
    warning = ArtifactFileViewerWarning(code, message, tool=tool)
    return viewer_result_from_warnings((warning,))


def _tmux_completed_process(
    cmd: Sequence[str],
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            list(cmd),
            check=False,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None


def tmux_warning(
    code: str,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
) -> ArtifactFileViewerWarning:
    if result is not None:
        stderr = result.stderr.strip()
        if stderr:
            message = f"{message}: {stderr}"
    return ArtifactFileViewerWarning(code, message, tool="tmux")


def tmux_display(target: str, fmt: str) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(["tmux", "display-message", "-p", "-t", target, fmt])


def tmux_show_window_option(
    target: str,
    option: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(
        ["tmux", "show-options", "-wqv", "-t", target, option]
    )


def tmux_set_window_option(
    target: str,
    option: str,
    value: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(
        ["tmux", "set-option", "-wq", "-t", target, option, value]
    )


def tmux_set_pane_title(
    pane_id: str,
    title: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(["tmux", "select-pane", "-t", pane_id, "-T", title])
