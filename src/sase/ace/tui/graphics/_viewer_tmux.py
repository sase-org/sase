"""Tmux pane launch and control helpers for the terminal artifact viewer."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from ._viewer_tmux_common import (
    _ARTIFACT_NOTIFY_PID_ENV,
    _ARTIFACT_RETURN_PANE_ID_ENV,
    is_tmux_session,
)
from ._viewer_tmux_decoration import (
    TmuxPaneDecorationResult,
    TmuxPaneDecorationState,
    decorate_artifact_tmux_panes,
    restore_artifact_tmux_pane_decoration,
)
from ._viewer_types import (
    ArtifactViewerResult,
    ArtifactViewerWarning,
    ArtifactViewSpec,
    viewer_result_from_warnings,
)

__all__ = [
    "TmuxPaneDecorationResult",
    "TmuxPaneDecorationState",
    "artifact_tmux_pane_exists",
    "artifact_viewer_module_command",
    "close_artifact_tmux_pane",
    "decorate_artifact_tmux_panes",
    "is_tmux_session",
    "restore_artifact_tmux_pane_decoration",
    "select_tmux_pane",
    "toggle_artifact_tmux_pane_zoom",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files_in_tmux_pane",
]


def view_artifact_file_in_tmux_pane(
    path: str | Path,
    *,
    kind: str | None = None,
    zoom: bool = False,
) -> ArtifactViewerResult:
    """Launch the artifact viewer in a right-side tmux pane."""

    return view_artifact_files_in_tmux_pane(
        (ArtifactViewSpec(path, kind),),
        zoom=zoom,
    )


def view_artifact_files_in_tmux_pane(
    artifacts: Sequence[ArtifactViewSpec],
    *,
    zoom: bool = False,
) -> ArtifactViewerResult:
    """Launch one or more artifacts in a right-side tmux pane."""

    specs = tuple(artifacts)
    if not specs:
        warning = ArtifactViewerWarning("no_artifacts", "No artifacts to view")
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if shutil.which("tmux") is None:
        warning = ArtifactViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    viewer_command = artifact_viewer_module_command(specs)
    tmux_command = [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    if origin_pane_id := os.environ.get("TMUX_PANE"):
        tmux_command.extend(["-e", f"{_ARTIFACT_RETURN_PANE_ID_ENV}={origin_pane_id}"])
    if notify_pid := os.environ.get(_ARTIFACT_NOTIFY_PID_ENV):
        tmux_command.extend(["-e", f"{_ARTIFACT_NOTIFY_PID_ENV}={notify_pid}"])
    tmux_command.append(shlex.join(viewer_command))
    result = subprocess.run(
        tmux_command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactViewerWarning(
            "tmux_split_failed",
            f"tmux split-window failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    pane_id = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else None
    if zoom:
        if pane_id is None:
            warning = ArtifactViewerWarning(
                "missing_tmux_pane",
                "No tmux pane id to zoom",
                tool="tmux",
            )
            return ArtifactViewerResult(
                True,
                warning=warning.message,
                warnings=(warning,),
                pane_id=pane_id,
            )
        zoom_result = toggle_artifact_tmux_pane_zoom(pane_id)
        if not zoom_result.ok:
            return ArtifactViewerResult(
                True,
                warning=zoom_result.warning,
                warnings=zoom_result.warnings,
                pane_id=pane_id,
            )
    return ArtifactViewerResult(True, pane_id=pane_id)


def artifact_tmux_pane_exists(pane_id: str) -> bool:
    """Return whether *pane_id* currently resolves in tmux."""

    if not pane_id or shutil.which("tmux") is None:
        return False
    result = subprocess.run(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_id}"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def close_artifact_tmux_pane(pane_id: str) -> ArtifactViewerResult:
    """Close a tracked artifact viewer tmux pane."""

    if not pane_id:
        warning = ArtifactViewerWarning(
            "missing_tmux_pane",
            "No tmux pane id to close",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if pane_id == os.environ.get("TMUX_PANE"):
        warning = ArtifactViewerWarning(
            "refusing_current_tmux_pane",
            "Refusing to close the current tmux pane",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if shutil.which("tmux") is None:
        warning = ArtifactViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    result = subprocess.run(
        ["tmux", "kill-pane", "-t", pane_id],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactViewerWarning(
            "tmux_kill_failed",
            f"tmux kill-pane failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactViewerResult(True)


def select_tmux_pane(pane_id: str) -> ArtifactViewerResult:
    """Focus a tmux pane by id."""

    if not pane_id:
        warning = ArtifactViewerWarning(
            "missing_tmux_pane",
            "No tmux pane id to select",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if shutil.which("tmux") is None:
        warning = ArtifactViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    result = subprocess.run(
        ["tmux", "select-pane", "-t", pane_id],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactViewerWarning(
            "tmux_select_failed",
            f"tmux select-pane failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactViewerResult(True)


def toggle_artifact_tmux_pane_zoom(
    pane_id: str | None = None,
) -> ArtifactViewerResult:
    """Toggle tmux zoom for the current artifact viewer pane."""

    if not is_tmux_session():
        warning = ArtifactViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if shutil.which("tmux") is None:
        warning = ArtifactViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    tmux_command = ["tmux", "resize-pane", "-Z"]
    target_pane_id = pane_id if pane_id is not None else os.environ.get("TMUX_PANE")
    if target_pane_id:
        tmux_command.extend(["-t", target_pane_id])
    result = subprocess.run(
        tmux_command,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactViewerWarning(
            "tmux_zoom_failed",
            f"tmux resize-pane -Z failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactViewerResult(True)


def artifact_viewer_module_command(
    artifacts: str | Path | Sequence[ArtifactViewSpec],
    *,
    kind: str | None = None,
) -> list[str]:
    specs: tuple[ArtifactViewSpec, ...]
    if isinstance(artifacts, str | Path):
        specs = (ArtifactViewSpec(artifacts, kind),)
    else:
        specs = tuple(artifacts)
    command = [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
    ]
    if len(specs) == 1:
        if specs[0].kind is not None:
            command.extend(["--kind", str(specs[0].kind)])
    else:
        for spec in specs:
            command.extend(["--kind", "" if spec.kind is None else str(spec.kind)])
    command.extend(str(Path(spec.path).expanduser()) for spec in specs)
    return command
