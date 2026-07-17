"""Public launch helpers for the terminal artifact-file viewer."""

from __future__ import annotations

import os
import signal
import tempfile
from collections.abc import Sequence
from pathlib import Path

from ._viewer_artifact_files import artifact_file_view_spec
from ._viewer_loop import run_artifact_sequence_loop, run_artifact_text_viewer
from ._viewer_render import artifact_file_view_mode
from ._viewer_tmux import (
    TmuxPaneDecorationResult,
    TmuxPaneDecorationState,
    artifact_file_tmux_pane_exists,
    artifact_file_viewer_module_command,
    close_artifact_file_tmux_pane,
    decorate_artifact_file_tmux_panes,
    is_tmux_session,
    restore_artifact_file_tmux_pane_decoration,
    select_tmux_pane,
    toggle_artifact_file_tmux_pane_zoom,
    view_artifact_file_in_tmux_pane,
    view_artifact_files_in_tmux_pane,
)
from ._viewer_tmux_common import (
    _ARTIFACT_FILE_NOTIFY_PID_ENV,
    _ARTIFACT_RETURN_PANE_ID_ENV,
)
from ._viewer_types import (
    ArtifactFileLike,
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    ArtifactFileViewSpec,
    ImageViewerResult,
    viewer_result_from_warnings,
)

__all__ = [
    "TmuxPaneDecorationResult",
    "TmuxPaneDecorationState",
    "_artifact_file_view_spec",
    "artifact_file_view_spec",
    "artifact_file_tmux_pane_exists",
    "artifact_file_viewer_module_command",
    "close_artifact_file_tmux_pane",
    "decorate_artifact_file_tmux_panes",
    "is_tmux_session",
    "restore_artifact_file_tmux_pane_decoration",
    "select_tmux_pane",
    "toggle_artifact_file_tmux_pane_zoom",
    "view_registered_artifact_file",
    "view_registered_artifact_file_in_tmux_pane",
    "view_registered_artifact_files",
    "view_registered_artifact_files_in_tmux_pane",
    "view_artifact_file",
    "view_artifact_file_in_tmux_pane",
    "view_artifact_files",
    "view_artifact_files_in_tmux_pane",
    "view_image_file",
]

_artifact_file_view_spec = artifact_file_view_spec


class _ArtifactViewerSignalExit(SystemExit):
    """Exit raised by pane-close signals so normal cleanup still runs."""


def _notify_artifact_file_viewer_parent() -> None:
    """Notify the Ace parent process that the viewer pane is exiting."""
    notify_pid = os.environ.get(_ARTIFACT_FILE_NOTIFY_PID_ENV)
    if not notify_pid or not hasattr(signal, "SIGUSR1"):
        return
    try:
        pid = int(notify_pid)
    except ValueError:
        return
    if pid <= 0:
        return
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError:
        return


def _install_artifact_file_viewer_cleanup_signal_handlers() -> dict[int, object]:
    """Route pane shutdown signals through Python cleanup handlers."""
    if not os.environ.get(_ARTIFACT_FILE_NOTIFY_PID_ENV):
        return {}

    def _handle_exit_signal(_signum: int, _frame: object) -> None:
        raise _ArtifactViewerSignalExit(0)

    previous_handlers: dict[int, object] = {}
    for signal_number in (
        getattr(signal, "SIGHUP", None),
        getattr(signal, "SIGTERM", None),
    ):
        if signal_number is None:
            continue
        try:
            previous_handlers[int(signal_number)] = signal.signal(
                signal_number, _handle_exit_signal
            )
        except (OSError, RuntimeError, ValueError):
            continue
    return previous_handlers


def _restore_artifact_file_viewer_cleanup_signal_handlers(
    previous_handlers: dict[int, object],
) -> None:
    """Restore signal handlers changed by the artifact viewer process."""
    for signal_number, handler in previous_handlers.items():
        try:
            signal.signal(signal_number, handler)  # type: ignore[arg-type]
        except (OSError, RuntimeError, ValueError):
            continue


def view_registered_artifact_file(
    artifact: ArtifactFileLike,
) -> ArtifactFileViewerResult:
    """Open a registered artifact file with the terminal page viewer."""

    return view_registered_artifact_files((artifact,))


def view_registered_artifact_files(
    artifacts: Sequence[ArtifactFileLike],
) -> ArtifactFileViewerResult:
    """Open one or more registered artifact files with the terminal page viewer."""

    return view_artifact_files(
        tuple(_artifact_file_view_spec(artifact) for artifact in artifacts)
    )


def view_registered_artifact_file_in_tmux_pane(
    artifact: ArtifactFileLike,
    *,
    zoom: bool = False,
) -> ArtifactFileViewerResult:
    """Open a registered artifact file with the terminal viewer in a tmux pane."""

    return view_registered_artifact_files_in_tmux_pane((artifact,), zoom=zoom)


def view_registered_artifact_files_in_tmux_pane(
    artifacts: Sequence[ArtifactFileLike],
    *,
    zoom: bool = False,
) -> ArtifactFileViewerResult:
    """Open one or more registered artifact files in a tmux pane."""

    return view_artifact_files_in_tmux_pane(
        tuple(_artifact_file_view_spec(artifact) for artifact in artifacts),
        zoom=zoom,
    )


def view_artifact_file(
    path: str | Path,
    *,
    kind: str | None = None,
) -> ArtifactFileViewerResult:
    """Display an artifact in the terminal viewer."""

    return view_artifact_files((ArtifactFileViewSpec(path, kind),))


def view_artifact_files(
    artifacts: Sequence[ArtifactFileViewSpec],
) -> ArtifactFileViewerResult:
    """Display one or more artifacts in the terminal viewer."""

    specs = tuple(artifacts)
    if not specs:
        warning = ArtifactFileViewerWarning("no_artifacts", "No artifacts to view")
        return viewer_result_from_warnings((warning,))
    previous_handlers = _install_artifact_file_viewer_cleanup_signal_handlers()
    try:
        return_pane_id = os.environ.get(_ARTIFACT_RETURN_PANE_ID_ENV) or None
        with tempfile.TemporaryDirectory(prefix="sase-artifact-viewer-") as tmp:
            if (
                len(specs) == 1
                and artifact_file_view_mode(specs[0].path, kind=specs[0].kind) == "text"
            ):
                loop_result = run_artifact_text_viewer(
                    specs[0],
                    return_pane_id=return_pane_id,
                )
            else:
                loop_result = run_artifact_sequence_loop(
                    specs,
                    cache_root=tmp,
                    return_pane_id=return_pane_id,
                )
            if loop_result.warnings:
                return viewer_result_from_warnings(loop_result.warnings)
            if loop_result.returncode != 0:
                warning = ArtifactFileViewerWarning(
                    "kitten_failed",
                    f"kitten icat failed with exit code {loop_result.returncode}",
                    tool="kitten",
                )
                return viewer_result_from_warnings((warning,))
            return ArtifactFileViewerResult(True)
    finally:
        _restore_artifact_file_viewer_cleanup_signal_handlers(previous_handlers)
        _notify_artifact_file_viewer_parent()


def view_image_file(path: str) -> ImageViewerResult:
    """Compatibility wrapper for older image-only callers."""

    return view_artifact_file(path, kind="image")
