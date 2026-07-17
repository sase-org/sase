"""Tmux pane decoration helpers for the terminal artifact viewer."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from ._viewer_tmux_common import (
    is_tmux_session,
    tmux_display,
    tmux_set_pane_title,
    tmux_set_window_option,
    tmux_show_window_option,
    tmux_warning,
    tmux_warning_result,
)
from ._viewer_types import (
    ArtifactFileViewerResult,
    ArtifactFileViewerWarning,
    viewer_result_from_warnings,
)

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
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()


def _decoration_warning_result(
    code: str,
    message: str,
) -> TmuxPaneDecorationResult:
    warning = ArtifactFileViewerWarning(code, message, tool="tmux")
    return TmuxPaneDecorationResult(False, warning=message, warnings=(warning,))


def decorate_artifact_file_tmux_panes(
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
    warnings: list[ArtifactFileViewerWarning] = []
    option_snapshots: list[_TmuxWindowOptionSnapshot] = []
    title_snapshots: list[_TmuxPaneTitleSnapshot] = []

    for option in _TMUX_DECORATED_WINDOW_OPTIONS:
        result = tmux_show_window_option(target_pane_id, option)
        if result is None or result.returncode != 0:
            warnings.append(
                tmux_warning(
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
        result = tmux_display(pane_id, "#{pane_title}")
        if result is None or result.returncode != 0:
            warnings.append(
                tmux_warning(
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
        result = tmux_set_pane_title(origin_pane_id, _ARTIFACT_ORIGIN_PANE_TITLE)
        if result is None or result.returncode != 0:
            warnings.append(
                tmux_warning(
                    "tmux_pane_title_failed",
                    f"tmux could not set title for pane {origin_pane_id}",
                    result,
                )
            )

    result = tmux_set_pane_title(artifact_pane_id, _ARTIFACT_VIEWER_PANE_TITLE)
    if result is None or result.returncode != 0:
        warnings.append(
            tmux_warning(
                "tmux_pane_title_failed",
                f"tmux could not set title for pane {artifact_pane_id}",
                result,
            )
        )

    snapshotted_options = {snapshot.name for snapshot in option_snapshots}
    for option, value in _TMUX_ARTIFACT_BORDER_OPTIONS.items():
        if option not in snapshotted_options:
            continue
        result = tmux_set_window_option(target_pane_id, option, value)
        if result is None or result.returncode != 0:
            warnings.append(
                tmux_warning(
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


def restore_artifact_file_tmux_pane_decoration(
    state: TmuxPaneDecorationState,
) -> ArtifactFileViewerResult:
    """Restore tmux pane/window decoration saved before artifact viewing."""

    if shutil.which("tmux") is None:
        return tmux_warning_result(
            "missing_tmux",
            "tmux executable not found",
        )

    warnings: list[ArtifactFileViewerWarning] = []
    for option in state.window_options:
        result = tmux_set_window_option(
            state.target_pane_id,
            option.name,
            option.value,
        )
        if result is None or result.returncode != 0:
            warnings.append(
                tmux_warning(
                    "tmux_option_restore_failed",
                    f"tmux could not restore {option.name}",
                    result,
                )
            )

    for title in state.pane_titles:
        result = tmux_set_pane_title(title.pane_id, title.title)
        if result is None or result.returncode != 0:
            # The artifact pane is often already gone by signal/stale cleanup.
            # Missing title restores should not make normal close paths noisy.
            continue

    if warnings:
        return viewer_result_from_warnings(tuple(warnings))
    return ArtifactFileViewerResult(True)
