"""Public launch helpers for the terminal artifact viewer."""

from __future__ import annotations

import os
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ._viewer_loop import run_artifact_sequence_loop
from ._viewer_types import (
    ArtifactLike,
    ArtifactViewerResult,
    ArtifactViewerWarning,
    ArtifactViewSpec,
    ImageViewerResult,
    viewer_result_from_warnings,
)

_ARTIFACT_NOTIFY_PID_ENV = "SASE_ARTIFACT_NOTIFY_PID"
_ARTIFACT_RETURN_PANE_ID_ENV = "SASE_ARTIFACT_RETURN_PANE_ID"
_ARTIFACT_ORIGIN_PANE_TITLE = "SASE TUI"
_ARTIFACT_VIEWER_PANE_TITLE = "Artifact Viewer"
_TMUX_DECORATED_WINDOW_OPTIONS = (
    "pane-border-status",
    "pane-border-format",
    "pane-border-style",
    "pane-active-border-style",
)
_TMUX_ARTIFACT_BORDER_FORMAT = (
    "#{?pane_active,#[bold,reverse] active #[default] #{pane_title}, #{pane_title}}"
)
_TMUX_ARTIFACT_BORDER_OPTIONS = {
    "pane-border-status": "top",
    "pane-border-format": _TMUX_ARTIFACT_BORDER_FORMAT,
    "pane-border-style": "fg=colour244",
    "pane-active-border-style": "fg=colour46,bold",
}


@dataclass(frozen=True)
class _TmuxWindowOptionSnapshot:
    """Snapshot of a tmux window option before artifact pane decoration."""

    name: str
    value: str


@dataclass(frozen=True)
class _TmuxPaneTitleSnapshot:
    """Snapshot of a tmux pane title before artifact pane decoration."""

    pane_id: str
    title: str


@dataclass(frozen=True)
class TmuxPaneDecorationState:
    """State needed to restore tmux pane decoration after artifact viewing."""

    target_pane_id: str
    window_options: tuple[_TmuxWindowOptionSnapshot, ...]
    pane_titles: tuple[_TmuxPaneTitleSnapshot, ...]


@dataclass(frozen=True)
class TmuxPaneDecorationResult:
    """Result returned after trying to decorate tmux artifact panes."""

    ok: bool
    state: TmuxPaneDecorationState | None = None
    warning: str | None = None
    warnings: tuple[ArtifactViewerWarning, ...] = ()


class _ArtifactViewerSignalExit(SystemExit):
    """Exit raised by pane-close signals so normal cleanup still runs."""


def _warning_result(
    code: str,
    message: str,
    *,
    tool: str | None = "tmux",
) -> ArtifactViewerResult:
    warning = ArtifactViewerWarning(code, message, tool=tool)
    return viewer_result_from_warnings((warning,))


def _decoration_warning_result(
    code: str,
    message: str,
) -> TmuxPaneDecorationResult:
    warning = ArtifactViewerWarning(code, message, tool="tmux")
    return TmuxPaneDecorationResult(False, warning=message, warnings=(warning,))


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


def _tmux_warning(
    code: str,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
) -> ArtifactViewerWarning:
    if result is not None:
        stderr = result.stderr.strip()
        if stderr:
            message = f"{message}: {stderr}"
    return ArtifactViewerWarning(code, message, tool="tmux")


def _tmux_display(target: str, fmt: str) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(["tmux", "display-message", "-p", "-t", target, fmt])


def _tmux_show_window_option(
    target: str,
    option: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(
        ["tmux", "show-options", "-wqv", "-t", target, option]
    )


def _tmux_set_window_option(
    target: str,
    option: str,
    value: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(
        ["tmux", "set-option", "-wq", "-t", target, option, value]
    )


def _tmux_set_pane_title(
    pane_id: str,
    title: str,
) -> subprocess.CompletedProcess[str] | None:
    return _tmux_completed_process(["tmux", "select-pane", "-t", pane_id, "-T", title])


def _notify_artifact_viewer_parent() -> None:
    """Notify the Ace parent process that the viewer pane is exiting."""
    notify_pid = os.environ.get(_ARTIFACT_NOTIFY_PID_ENV)
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


def _install_artifact_viewer_cleanup_signal_handlers() -> dict[int, object]:
    """Route pane shutdown signals through Python cleanup handlers."""
    if not os.environ.get(_ARTIFACT_NOTIFY_PID_ENV):
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


def _restore_artifact_viewer_cleanup_signal_handlers(
    previous_handlers: dict[int, object],
) -> None:
    """Restore signal handlers changed by the artifact viewer process."""
    for signal_number, handler in previous_handlers.items():
        try:
            signal.signal(signal_number, handler)  # type: ignore[arg-type]
        except (OSError, RuntimeError, ValueError):
            continue


def view_agent_artifact(artifact: ArtifactLike) -> ArtifactViewerResult:
    """Open an agent artifact with the terminal page viewer."""

    return view_agent_artifacts((artifact,))


def view_agent_artifacts(
    artifacts: Sequence[ArtifactLike],
) -> ArtifactViewerResult:
    """Open one or more agent artifacts with the terminal page viewer."""

    return view_artifact_files(
        tuple(
            ArtifactViewSpec(artifact.path, getattr(artifact, "kind", None))
            for artifact in artifacts
        )
    )


def view_agent_artifact_in_tmux_pane(artifact: ArtifactLike) -> ArtifactViewerResult:
    """Open an agent artifact with the terminal page viewer in a tmux pane."""

    return view_agent_artifacts_in_tmux_pane((artifact,))


def view_agent_artifacts_in_tmux_pane(
    artifacts: Sequence[ArtifactLike],
) -> ArtifactViewerResult:
    """Open one or more agent artifacts in a tmux pane."""

    return view_artifact_files_in_tmux_pane(
        tuple(
            ArtifactViewSpec(artifact.path, getattr(artifact, "kind", None))
            for artifact in artifacts
        )
    )


def view_artifact_file(
    path: str | Path,
    *,
    kind: str | None = None,
) -> ArtifactViewerResult:
    """Render and display an artifact with ``kitten icat`` pages."""

    return view_artifact_files((ArtifactViewSpec(path, kind),))


def view_artifact_files(
    artifacts: Sequence[ArtifactViewSpec],
) -> ArtifactViewerResult:
    """Render and display one or more artifacts with ``kitten icat`` pages."""

    specs = tuple(artifacts)
    if not specs:
        warning = ArtifactViewerWarning("no_artifacts", "No artifacts to view")
        return viewer_result_from_warnings((warning,))
    previous_handlers = _install_artifact_viewer_cleanup_signal_handlers()
    try:
        return_pane_id = os.environ.get(_ARTIFACT_RETURN_PANE_ID_ENV) or None
        with tempfile.TemporaryDirectory(prefix="sase-artifact-viewer-") as tmp:
            loop_result = run_artifact_sequence_loop(
                specs,
                cache_root=tmp,
                return_pane_id=return_pane_id,
            )
            if loop_result.warnings:
                return viewer_result_from_warnings(loop_result.warnings)
            if loop_result.returncode != 0:
                warning = ArtifactViewerWarning(
                    "kitten_failed",
                    f"kitten icat failed with exit code {loop_result.returncode}",
                    tool="kitten",
                )
                return viewer_result_from_warnings((warning,))
            return ArtifactViewerResult(True)
    finally:
        _restore_artifact_viewer_cleanup_signal_handlers(previous_handlers)
        _notify_artifact_viewer_parent()


def view_image_file(path: str) -> ImageViewerResult:
    """Compatibility wrapper for image-only notification/file-panel callers."""

    return view_artifact_file(path, kind="image")


def is_tmux_session() -> bool:
    """Return whether the current process is running inside tmux."""

    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


def decorate_artifact_tmux_panes(
    artifact_pane_id: str,
) -> TmuxPaneDecorationResult:
    """Add window-scoped tmux pane decoration for artifact viewer focus state."""

    if not artifact_pane_id:
        return _decoration_warning_result(
            "missing_tmux_pane",
            "No tmux pane id to decorate",
        )
    if not is_tmux_session():
        return _decoration_warning_result(
            "not_in_tmux",
            "Not running inside tmux",
        )
    if shutil.which("tmux") is None:
        return _decoration_warning_result(
            "missing_tmux",
            "tmux executable not found",
        )

    origin_pane_id = os.environ.get("TMUX_PANE") or None
    target_pane_id = origin_pane_id or artifact_pane_id
    warnings: list[ArtifactViewerWarning] = []
    option_snapshots: list[_TmuxWindowOptionSnapshot] = []
    title_snapshots: list[_TmuxPaneTitleSnapshot] = []

    for option in _TMUX_DECORATED_WINDOW_OPTIONS:
        result = _tmux_show_window_option(target_pane_id, option)
        if result is None or result.returncode != 0:
            warnings.append(
                _tmux_warning(
                    "tmux_option_snapshot_failed",
                    f"tmux could not read {option}",
                    result,
                )
            )
            continue
        option_snapshots.append(
            _TmuxWindowOptionSnapshot(option, result.stdout.rstrip("\n"))
        )

    for pane_id in (origin_pane_id, artifact_pane_id):
        if pane_id is None:
            continue
        result = _tmux_display(pane_id, "#{pane_title}")
        if result is None or result.returncode != 0:
            warnings.append(
                _tmux_warning(
                    "tmux_pane_title_snapshot_failed",
                    f"tmux could not read title for pane {pane_id}",
                    result,
                )
            )
            continue
        title_snapshots.append(
            _TmuxPaneTitleSnapshot(pane_id, result.stdout.rstrip("\n"))
        )

    if origin_pane_id is not None:
        result = _tmux_set_pane_title(origin_pane_id, _ARTIFACT_ORIGIN_PANE_TITLE)
        if result is None or result.returncode != 0:
            warnings.append(
                _tmux_warning(
                    "tmux_pane_title_failed",
                    f"tmux could not set title for pane {origin_pane_id}",
                    result,
                )
            )

    result = _tmux_set_pane_title(artifact_pane_id, _ARTIFACT_VIEWER_PANE_TITLE)
    if result is None or result.returncode != 0:
        warnings.append(
            _tmux_warning(
                "tmux_pane_title_failed",
                f"tmux could not set title for pane {artifact_pane_id}",
                result,
            )
        )

    snapshotted_options = {snapshot.name for snapshot in option_snapshots}
    for option, value in _TMUX_ARTIFACT_BORDER_OPTIONS.items():
        if option not in snapshotted_options:
            continue
        result = _tmux_set_window_option(target_pane_id, option, value)
        if result is None or result.returncode != 0:
            warnings.append(
                _tmux_warning(
                    "tmux_option_set_failed",
                    f"tmux could not set {option}",
                    result,
                )
            )

    state = TmuxPaneDecorationState(
        target_pane_id=target_pane_id,
        window_options=tuple(option_snapshots),
        pane_titles=tuple(title_snapshots),
    )
    return TmuxPaneDecorationResult(
        True,
        state=state,
        warning=warnings[0].message if warnings else None,
        warnings=tuple(warnings),
    )


def restore_artifact_tmux_pane_decoration(
    state: TmuxPaneDecorationState,
) -> ArtifactViewerResult:
    """Restore tmux pane/window decoration saved before artifact viewing."""

    if shutil.which("tmux") is None:
        return _warning_result(
            "missing_tmux",
            "tmux executable not found",
        )

    warnings: list[ArtifactViewerWarning] = []
    for option in state.window_options:
        result = _tmux_set_window_option(
            state.target_pane_id,
            option.name,
            option.value,
        )
        if result is None or result.returncode != 0:
            warnings.append(
                _tmux_warning(
                    "tmux_option_restore_failed",
                    f"tmux could not restore {option.name}",
                    result,
                )
            )

    for title in state.pane_titles:
        result = _tmux_set_pane_title(title.pane_id, title.title)
        if result is None or result.returncode != 0:
            # The artifact pane is often already gone by signal/stale cleanup.
            # Missing title restores should not make normal close paths noisy.
            continue

    if warnings:
        return viewer_result_from_warnings(tuple(warnings))
    return ArtifactViewerResult(True)


def view_artifact_file_in_tmux_pane(
    path: str | Path,
    *,
    kind: str | None = None,
) -> ArtifactViewerResult:
    """Launch the artifact viewer in a right-side tmux pane."""

    return view_artifact_files_in_tmux_pane((ArtifactViewSpec(path, kind),))


def view_artifact_files_in_tmux_pane(
    artifacts: Sequence[ArtifactViewSpec],
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
