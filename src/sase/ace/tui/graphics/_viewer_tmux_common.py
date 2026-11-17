"""Shared tmux helpers for terminal artifact viewer launches."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence

from ._viewer_types import (
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    viewer_result_from_warnings,
)

_ARTIFACT_FILE_NOTIFY_PID_ENV = "SASE_ARTIFACT_FILE_NOTIFY_PID"
_ARTIFACT_RETURN_PANE_ID_ENV = "SASE_ARTIFACT_RETURN_PANE_ID"
ARTIFACT_VIEWER_OPEN_ID_ENV = "SASE_ARTIFACT_VIEWER_OPEN_ID"
ARTIFACT_VIEWER_OPEN_T0_ENV = "SASE_ARTIFACT_VIEWER_OPEN_T0"
TMUX_SUBPROCESS_TIMEOUT_SECONDS = 2
_TMUX_TIMEOUT_RETURNCODE = 124


def tmux_timeout_warning(action: str) -> ArtifactFileViewerWarning:
    """Return the structured warning used when a tmux subprocess times out."""

    return ArtifactFileViewerWarning(
        "tmux_timeout",
        f"tmux {action} timed out after {TMUX_SUBPROCESS_TIMEOUT_SECONDS}s",
        tool="tmux",
    )


def tmux_process_timed_out(
    result: subprocess.CompletedProcess[str] | None,
) -> bool:
    """Return whether *result* is the timeout sentinel from a tmux helper."""

    return (
        result is not None
        and result.returncode == _TMUX_TIMEOUT_RETURNCODE
        and (result.stderr or "").startswith("timed out after ")
    )


def is_tmux_session() -> bool:
    """Return whether the current process is running inside tmux."""

    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


def tmux_binary_available() -> bool:
    """Return whether a ``tmux`` executable is on ``PATH``."""

    return shutil.which("tmux") is not None


def tmux_warning_result(
    code: str,
    message: str,
    *,
    tool: str | None = "tmux",
) -> ArtifactFileViewerResult:
    warning = ArtifactFileViewerWarning(code, message, tool=tool)
    return viewer_result_from_warnings((warning,))


def tmux_completed_process(
    cmd: Sequence[str],
) -> subprocess.CompletedProcess[str] | None:
    """Run a tmux argv with the shared 2s timeout, or return None if missing."""

    argv = list(cmd)
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            timeout=TMUX_SUBPROCESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            argv,
            _TMUX_TIMEOUT_RETURNCODE,
            "",
            f"timed out after {TMUX_SUBPROCESS_TIMEOUT_SECONDS}s",
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
    return tmux_completed_process(["tmux", "display-message", "-p", "-t", target, fmt])


def tmux_show_window_option(
    target: str,
    option: str,
) -> subprocess.CompletedProcess[str] | None:
    return tmux_completed_process(
        ["tmux", "show-options", "-wqv", "-t", target, option]
    )


def tmux_set_window_option(
    target: str,
    option: str,
    value: str,
) -> subprocess.CompletedProcess[str] | None:
    return tmux_completed_process(
        ["tmux", "set-option", "-wq", "-t", target, option, value]
    )


def tmux_set_pane_title(
    pane_id: str,
    title: str,
) -> subprocess.CompletedProcess[str] | None:
    return tmux_completed_process(["tmux", "select-pane", "-t", pane_id, "-T", title])
