"""Public launch helpers for the terminal artifact viewer."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
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
    with tempfile.TemporaryDirectory(prefix="sase-artifact-viewer-") as tmp:
        loop_result = run_artifact_sequence_loop(specs, cache_root=tmp)
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


def view_image_file(path: str) -> ImageViewerResult:
    """Compatibility wrapper for image-only notification/file-panel callers."""

    return view_artifact_file(path, kind="image")


def is_tmux_session() -> bool:
    """Return whether the current process is running inside tmux."""

    return bool(os.environ.get("TMUX") or os.environ.get("TMUX_PANE"))


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
    tmux_command = ["tmux", "split-window", "-h", shlex.join(viewer_command)]
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
