"""Tmux pane launch and control helpers for the terminal artifact viewer."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ._viewer_loop_media import (
    ARTIFACT_VIEWER_VIDEO_CONFIG_ENV,
    load_merged_artifact_video_playback_config,
    serialize_video_playback_config,
)
from ._viewer_tmux_common import (
    ARTIFACT_VIEWER_OPEN_ID_ENV,
    ARTIFACT_VIEWER_OPEN_T0_ENV,
    _ARTIFACT_FILE_NOTIFY_PID_ENV,
    _ARTIFACT_RETURN_PANE_ID_ENV,
    tmux_completed_process,
    is_tmux_session,
    tmux_binary_available,
    tmux_process_timed_out,
    tmux_timeout_warning,
)
from ._viewer_tmux_decoration import (
    TmuxPaneDecorationResult,
    TmuxPaneDecorationState,
    decorate_artifact_file_tmux_panes,
    restore_artifact_file_tmux_pane_decoration,
)
from ._viewer_types import (
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
    viewer_result_from_warnings,
)

__all__ = [
    "ArtifactViewerLaunchContext",
    "TmuxPaneDecorationResult",
    "TmuxPaneDecorationState",
    "artifact_file_tmux_pane_exists",
    "artifact_file_viewer_module_command",
    "close_artifact_file_tmux_pane",
    "decorate_artifact_file_tmux_panes",
    "is_tmux_session",
    "restore_artifact_file_tmux_pane_decoration",
    "select_tmux_pane",
    "toggle_artifact_file_tmux_pane_zoom",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files_in_tmux_pane",
]


@dataclass(frozen=True)
class ArtifactViewerLaunchContext:
    """Explicit tmux-pane launch env so callers need not mutate ``os.environ``."""

    notify_pid: int | None = None
    return_pane_id: str | None = None
    extra_env: Mapping[str, str] = field(default_factory=dict)
    open_id: str | None = None
    open_t0: float | None = None


def _run_tmux_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a tmux argv with the shared launch timeout."""

    result = tmux_completed_process(command)
    if result is None:
        return subprocess.CompletedProcess(
            list(command),
            127,
            "",
            "tmux executable not found",
        )
    return result


def view_artifact_file_in_tmux_pane(
    path: str | Path,
    *,
    kind: str | None = None,
    zoom: bool = False,
    launch: ArtifactViewerLaunchContext | None = None,
) -> ArtifactFileViewerResult:
    """Launch the artifact viewer in a right-side tmux pane."""

    return view_artifact_files_in_tmux_pane(
        (ArtifactFileViewSpec(path, kind),),
        zoom=zoom,
        launch=launch,
    )


def _tmux_split_env_pairs(
    launch: ArtifactViewerLaunchContext | None,
) -> list[tuple[str, str]]:
    """Build ``split-window -e`` pairs from *launch* or process-env defaults."""

    extra_env = dict(launch.extra_env) if launch is not None else {}
    if launch is not None:
        if launch.open_id:
            extra_env.setdefault(ARTIFACT_VIEWER_OPEN_ID_ENV, launch.open_id)
        if launch.open_t0 is not None:
            extra_env.setdefault(ARTIFACT_VIEWER_OPEN_T0_ENV, str(launch.open_t0))
        notify_pid = str(launch.notify_pid) if launch.notify_pid is not None else None
        origin_pane_id = launch.return_pane_id
    else:
        notify_pid = os.environ.get(_ARTIFACT_FILE_NOTIFY_PID_ENV)
        origin_pane_id = None
    if not origin_pane_id:
        origin_pane_id = os.environ.get("TMUX_PANE")

    pairs: list[tuple[str, str]] = []
    added: set[str] = set()

    def _add(key: str, value: str | None) -> None:
        if not value or key in added:
            return
        pairs.append((key, value))
        added.add(key)

    _add(_ARTIFACT_RETURN_PANE_ID_ENV, origin_pane_id)
    _add(_ARTIFACT_FILE_NOTIFY_PID_ENV, notify_pid)
    snapshot = serialize_video_playback_config(
        load_merged_artifact_video_playback_config()
    )
    _add(ARTIFACT_VIEWER_VIDEO_CONFIG_ENV, snapshot)
    for key in ("SASE_TUI_TRACE", "SASE_TUI_TRACE_PATH"):
        _add(key, extra_env.get(key) or os.environ.get(key))
    for key, value in extra_env.items():
        _add(key, value)
    return pairs


def view_artifact_files_in_tmux_pane(
    artifacts: Sequence[ArtifactFileViewSpec],
    *,
    zoom: bool = False,
    launch: ArtifactViewerLaunchContext | None = None,
) -> ArtifactFileViewerResult:
    """Launch one or more artifacts in a right-side tmux pane."""

    specs = tuple(artifacts)
    if not specs:
        warning = ArtifactFileViewerWarning("no_artifacts", "No artifacts to view")
        return viewer_result_from_warnings((warning,))
    if any(not spec.path for spec in specs):
        warning = ArtifactFileViewerWarning(
            "missing_artifact_path",
            "Artifact content is not available on disk",
        )
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactFileViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not tmux_binary_available():
        warning = ArtifactFileViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    viewer_command = artifact_file_viewer_module_command(specs)
    tmux_command = [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    for key, value in _tmux_split_env_pairs(launch):
        tmux_command.extend(["-e", f"{key}={value}"])
    tmux_command.append(shlex.join(viewer_command))
    result = _run_tmux_command(tmux_command)
    if result.returncode != 0:
        if tmux_process_timed_out(result):
            return viewer_result_from_warnings((tmux_timeout_warning("split-window"),))
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactFileViewerWarning(
            "tmux_split_failed",
            f"tmux split-window failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    pane_id = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else None
    if zoom:
        if pane_id is None:
            warning = ArtifactFileViewerWarning(
                "missing_tmux_pane",
                "No tmux pane id to zoom",
                tool="tmux",
            )
            return ArtifactFileViewerResult(
                True,
                warning=warning.message,
                warnings=(warning,),
                pane_id=pane_id,
            )
        zoom_result = toggle_artifact_file_tmux_pane_zoom(pane_id)
        if not zoom_result.ok:
            return ArtifactFileViewerResult(
                True,
                warning=zoom_result.warning,
                warnings=zoom_result.warnings,
                pane_id=pane_id,
            )
    return ArtifactFileViewerResult(True, pane_id=pane_id)


def artifact_file_tmux_pane_exists(pane_id: str) -> bool:
    """Return whether *pane_id* currently resolves in tmux."""

    if not pane_id or not tmux_binary_available():
        return False
    result = _run_tmux_command(
        ["tmux", "display-message", "-p", "-t", pane_id, "#{pane_id}"]
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def close_artifact_file_tmux_pane(pane_id: str) -> ArtifactFileViewerResult:
    """Close a tracked artifact viewer tmux pane."""

    if not pane_id:
        warning = ArtifactFileViewerWarning(
            "missing_tmux_pane",
            "No tmux pane id to close",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if pane_id == os.environ.get("TMUX_PANE"):
        warning = ArtifactFileViewerWarning(
            "refusing_current_tmux_pane",
            "Refusing to close the current tmux pane",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactFileViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not tmux_binary_available():
        warning = ArtifactFileViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    result = _run_tmux_command(["tmux", "kill-pane", "-t", pane_id])
    if result.returncode != 0:
        if tmux_process_timed_out(result):
            return viewer_result_from_warnings((tmux_timeout_warning("kill-pane"),))
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactFileViewerWarning(
            "tmux_kill_failed",
            f"tmux kill-pane failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactFileViewerResult(True)


def select_tmux_pane(pane_id: str) -> ArtifactFileViewerResult:
    """Focus a tmux pane by id."""

    if not pane_id:
        warning = ArtifactFileViewerWarning(
            "missing_tmux_pane",
            "No tmux pane id to select",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not is_tmux_session():
        warning = ArtifactFileViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not tmux_binary_available():
        warning = ArtifactFileViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    result = _run_tmux_command(["tmux", "select-pane", "-t", pane_id])
    if result.returncode != 0:
        if tmux_process_timed_out(result):
            return viewer_result_from_warnings((tmux_timeout_warning("select-pane"),))
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactFileViewerWarning(
            "tmux_select_failed",
            f"tmux select-pane failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactFileViewerResult(True)


def toggle_artifact_file_tmux_pane_zoom(
    pane_id: str | None = None,
) -> ArtifactFileViewerResult:
    """Toggle tmux zoom for the current artifact viewer pane."""

    if not is_tmux_session():
        warning = ArtifactFileViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))
    if not tmux_binary_available():
        warning = ArtifactFileViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    tmux_command = ["tmux", "resize-pane", "-Z"]
    target_pane_id = pane_id if pane_id is not None else os.environ.get("TMUX_PANE")
    if target_pane_id:
        tmux_command.extend(["-t", target_pane_id])
    result = _run_tmux_command(tmux_command)
    if result.returncode != 0:
        if tmux_process_timed_out(result):
            return viewer_result_from_warnings(
                (tmux_timeout_warning("resize-pane -Z"),)
            )
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        warning = ArtifactFileViewerWarning(
            "tmux_zoom_failed",
            f"tmux resize-pane -Z failed with exit code {result.returncode}{suffix}",
            tool="tmux",
        )
        return viewer_result_from_warnings((warning,))

    return ArtifactFileViewerResult(True)


def artifact_file_viewer_module_command(
    artifacts: str | Path | Sequence[ArtifactFileViewSpec],
    *,
    kind: str | None = None,
) -> list[str]:
    specs: tuple[ArtifactFileViewSpec, ...]
    if isinstance(artifacts, str | Path):
        specs = (ArtifactFileViewSpec(artifacts, kind),)
    else:
        specs = tuple(artifacts)
    if any(not spec.path for spec in specs):
        raise ValueError("artifact view spec requires a path")
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
