"""Implementation of ``sase artifact open``."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

from sase.artifact_cli.references import (
    ResolvedArtifactReference,
    resolution_error_lines,
    resolved_file_path,
    resolve_cli_reference,
)


_TEXT_APPLICATION_MIME_TYPES = {
    "application/json",
    "application/toml",
    "application/x-yaml",
    "application/xml",
    "application/yaml",
}


def handle_open(args: argparse.Namespace) -> int:
    """Resolve and open one artifact with a safe, bounded viewer."""

    try:
        result = resolve_cli_reference(args.reference)
    except (RuntimeError, ValueError) as exc:
        print(f"Error: malformed artifact reference: {exc}", file=sys.stderr)
        return 1

    if result.parsed.kind_type == "commit":
        print(
            "Error: commit: references have no filesystem viewer; "
            f"use `sase artifact show {result.canonical_reference}`",
            file=sys.stderr,
        )
        return 2
    if result.parsed.kind_type == "bug":
        return _open_bug(result)
    try:
        path = resolved_file_path(result)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(
            f"Error: failed to materialize {result.canonical_reference}: {exc}",
            file=sys.stderr,
        )
        for line in resolution_error_lines(result)[1:]:
            print(line, file=sys.stderr)
        return 1
    if path is None:
        for line in resolution_error_lines(result):
            print(line, file=sys.stderr)
        return 1

    path = Path(path).expanduser().resolve(strict=False)
    command = _viewer_command(path, result)
    if command is None:
        return 1
    try:
        completed = subprocess.run(command, check=False)
    except OSError as exc:
        print(f"Error: failed to open resolved artifact {path}: {exc}", file=sys.stderr)
        return 1
    if completed.returncode != 0:
        print(
            f"Error: viewer {command[0]!r} failed for {path} with exit code "
            f"{completed.returncode}",
            file=sys.stderr,
        )
        return 1
    return 0


def _open_bug(result: ResolvedArtifactReference) -> int:
    if result.resolution.status not in {"exact", "drifted"}:
        for line in resolution_error_lines(result):
            print(line, file=sys.stderr)
        return 1
    locator = result.resolution.locator
    number = result.parsed.payload.number
    if locator is None or number is None:
        print(
            f"Error: bug reference did not resolve to a tracker issue: "
            f"{result.canonical_reference}",
            file=sys.stderr,
        )
        return 1
    project = locator.rsplit("#", 1)[0]
    try:
        from sase.ace.tui.artifacts_bugs import issue_url_for_number

        url = issue_url_for_number(project, number)
        opened = webbrowser.open(url)
    except Exception as exc:
        print(
            f"Error: failed to open bug reference {result.canonical_reference}: {exc}",
            file=sys.stderr,
        )
        return 1
    if not opened:
        print(
            f"Error: no browser accepted bug URL {url}",
            file=sys.stderr,
        )
        return 1
    return 0


def _viewer_command(
    path: Path,
    result: ResolvedArtifactReference,
) -> list[str] | None:
    from sase.ace.tui.graphics import (
        artifact_image_area,
        artifact_text_viewer_command,
        artifact_video_player_command,
        is_supported_image_path,
        is_supported_video_path,
        kitten_icat_command,
        load_artifact_video_playback_config,
    )

    kind = result.file.kind if result.file is not None else result.parsed.kind
    mime_type = (
        result.file.mime_type
        if result.file is not None and result.file.mime_type
        else mimetypes.guess_type(path)[0]
    )
    if (
        kind == "image"
        or is_supported_image_path(path)
        or _mime_starts(mime_type, "image/")
    ):
        if not _viewer_available("kitten", path):
            return None
        command = kitten_icat_command(path, artifact_image_area())
        command.insert(-1, "--")
        return command
    if is_supported_video_path(path) or _mime_starts(mime_type, "video/"):
        if not _viewer_available("mpv", path):
            return None
        return artifact_video_player_command(
            path,
            artifact_image_area(),
            load_artifact_video_playback_config(),
        )
    if _is_pdf(path, kind=kind, mime_type=mime_type):
        return _xdg_open_command(path)
    if _is_text(kind=kind, mime_type=mime_type):
        return artifact_text_viewer_command(path)
    return _xdg_open_command(path)


def _xdg_open_command(path: Path) -> list[str] | None:
    if not _viewer_available("xdg-open", path):
        return None
    return ["xdg-open", "--", str(path)]


def _viewer_available(command: str, path: Path) -> bool:
    if shutil.which(command) is not None:
        return True
    print(
        f"Error: viewer {command!r} is unavailable for resolved artifact {path}",
        file=sys.stderr,
    )
    return False


def _mime_starts(mime_type: str | None, prefix: str) -> bool:
    return bool(mime_type and mime_type.startswith(prefix))


def _is_pdf(path: Path, *, kind: str, mime_type: str | None) -> bool:
    return (
        kind == "pdf" or mime_type == "application/pdf" or path.suffix.lower() == ".pdf"
    )


def _is_text(*, kind: str, mime_type: str | None) -> bool:
    return (
        kind in {"chat", "markdown", "plan"}
        or _mime_starts(mime_type, "text/")
        or mime_type in _TEXT_APPLICATION_MIME_TYPES
    )


__all__ = ["handle_open"]
