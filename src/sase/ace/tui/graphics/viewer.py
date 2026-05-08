"""Artifact-aware terminal viewer helpers for TUI surfaces."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import termios
import tty
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from sase.attachments.markdown_pdf import PDF_ENGINES, render_markdown_pdf

from .images import is_supported_image_path

ArtifactViewMode = Literal["image", "markdown", "pdf"]

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})


class _ArtifactLike(Protocol):
    """Minimal artifact shape consumed by the viewer."""

    path: str
    kind: str


@dataclass(frozen=True)
class ArtifactViewerWarning:
    """Structured warning returned by artifact rendering/viewer helpers."""

    code: str
    message: str
    tool: str | None = None


@dataclass(frozen=True)
class ArtifactRenderResult:
    """Rendered artifact pages ready for terminal display."""

    pages: tuple[Path, ...]
    warnings: tuple[ArtifactViewerWarning, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether at least one displayable page was produced."""
        return bool(self.pages) and not self.warnings


@dataclass(frozen=True)
class ArtifactViewerResult:
    """Result returned after trying to open an artifact outside Textual."""

    ok: bool
    warning: str | None = None
    warnings: tuple[ArtifactViewerWarning, ...] = ()


ImageViewerResult = ArtifactViewerResult


def view_agent_artifact(artifact: _ArtifactLike) -> ArtifactViewerResult:
    """Open an agent artifact with the terminal page viewer."""

    return view_artifact_file(artifact.path, kind=artifact.kind)


def view_agent_artifact_in_tmux_pane(artifact: _ArtifactLike) -> ArtifactViewerResult:
    """Open an agent artifact with the terminal page viewer in a tmux pane."""

    return view_artifact_file_in_tmux_pane(artifact.path, kind=artifact.kind)


def view_artifact_file(
    path: str | Path,
    *,
    kind: str | None = None,
) -> ArtifactViewerResult:
    """Render and display an artifact with ``kitten icat`` pages."""

    with tempfile.TemporaryDirectory(prefix="sase-artifact-viewer-") as tmp:
        rendered = render_artifact_pages(path, kind=kind, cache_dir=tmp)
        if rendered.warnings:
            return _viewer_result_from_warnings(rendered.warnings)
        loop_result = run_artifact_page_loop(rendered.pages)
        if loop_result.returncode != 0:
            warning = ArtifactViewerWarning(
                "kitten_failed",
                f"kitten icat failed with exit code {loop_result.returncode}",
                tool="kitten",
            )
            return _viewer_result_from_warnings((warning,))
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

    if not is_tmux_session():
        warning = ArtifactViewerWarning(
            "not_in_tmux",
            "Not running inside tmux",
            tool="tmux",
        )
        return _viewer_result_from_warnings((warning,))
    if shutil.which("tmux") is None:
        warning = ArtifactViewerWarning(
            "missing_tmux",
            "tmux executable not found",
            tool="tmux",
        )
        return _viewer_result_from_warnings((warning,))

    viewer_command = _artifact_viewer_module_command(path, kind=kind)
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
        return _viewer_result_from_warnings((warning,))

    return ArtifactViewerResult(True)


def render_artifact_pages(
    path: str | Path,
    *,
    kind: str | None = None,
    cache_dir: str | Path | None = None,
) -> ArtifactRenderResult:
    """Render *path* into one or more image pages for terminal display."""

    expanded = Path(path).expanduser().resolve(strict=False)
    mode = artifact_view_mode(expanded, kind=kind)
    if mode is None:
        return ArtifactRenderResult(
            (),
            (
                ArtifactViewerWarning(
                    "unsupported_artifact_kind",
                    "Unsupported artifact type",
                ),
            ),
        )
    if not expanded.exists():
        return ArtifactRenderResult(
            (),
            (
                ArtifactViewerWarning(
                    "artifact_not_found",
                    "Artifact file not found",
                ),
            ),
        )

    warnings = validate_artifact_viewer_dependencies(mode)
    if warnings:
        return ArtifactRenderResult((), tuple(warnings))

    if mode == "image":
        return ArtifactRenderResult((expanded,))

    render_root = (
        Path(cache_dir).expanduser()
        if cache_dir is not None
        else Path(tempfile.mkdtemp(prefix="sase-artifact-pages-"))
    )
    return _render_paginated_artifact(expanded, mode, render_root)


def artifact_view_mode(
    path: str | Path,
    *,
    kind: str | None = None,
) -> ArtifactViewMode | None:
    """Return the terminal view mode for an artifact kind/path pair."""

    suffix = Path(path).suffix.lower()
    normalized = str(kind).lower() if kind is not None else ""
    if normalized == "image" or is_supported_image_path(path):
        return "image"
    if normalized == "pdf" or suffix == ".pdf":
        return "pdf"
    if normalized == "markdown" or suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    if normalized in {"chat", "plan", "file"} and suffix in _MARKDOWN_SUFFIXES:
        return "markdown"
    return None


def validate_artifact_viewer_dependencies(
    mode: ArtifactViewMode,
) -> tuple[ArtifactViewerWarning, ...]:
    """Return missing terminal/rendering dependencies for *mode*."""

    warnings: list[ArtifactViewerWarning] = []
    if shutil.which("kitten") is None:
        warnings.append(
            ArtifactViewerWarning(
                "missing_kitten",
                "kitten executable not found",
                tool="kitten",
            )
        )
    if mode in {"markdown", "pdf"} and shutil.which("pdftoppm") is None:
        warnings.append(
            ArtifactViewerWarning(
                "missing_pdftoppm",
                "pdftoppm executable not found",
                tool="pdftoppm",
            )
        )
    if mode == "markdown":
        if shutil.which("pandoc") is None:
            warnings.append(
                ArtifactViewerWarning(
                    "missing_pandoc",
                    "pandoc executable not found",
                    tool="pandoc",
                )
            )
        if not any(shutil.which(engine) for engine in PDF_ENGINES):
            warnings.append(
                ArtifactViewerWarning(
                    "missing_pdf_engine",
                    "No PDF engine found",
                    tool=",".join(PDF_ENGINES),
                )
            )
    return tuple(warnings)


def convert_pdf_to_png_pages(
    pdf_path: str | Path,
    output_dir: str | Path,
) -> ArtifactRenderResult:
    """Convert a PDF into PNG pages with ``pdftoppm -png`` semantics."""

    pdf = Path(pdf_path).expanduser()
    out_dir = Path(output_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    result = subprocess.run(
        ["pdftoppm", "-png", str(pdf), str(prefix)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        suffix = f": {stderr}" if stderr else ""
        return ArtifactRenderResult(
            (),
            (
                ArtifactViewerWarning(
                    "pdftoppm_failed",
                    f"pdftoppm failed with exit code {result.returncode}{suffix}",
                    tool="pdftoppm",
                ),
            ),
        )

    pages = tuple(_collect_pdftoppm_pages(prefix))
    if not pages:
        return ArtifactRenderResult(
            (),
            (
                ArtifactViewerWarning(
                    "no_pdf_pages",
                    "pdftoppm did not produce any PNG pages",
                    tool="pdftoppm",
                ),
            ),
        )
    return ArtifactRenderResult(pages)


@dataclass(frozen=True)
class _PageLoopResult:
    """Terminal page loop subprocess status."""

    returncode: int = 0


def page_index_after_key(current_index: int, key: str, page_count: int) -> int | None:
    """Return the next page index, or ``None`` when the loop should quit."""

    normalized = key.lower()
    if normalized == "q":
        return None
    if normalized == "r":
        return current_index
    if page_count <= 1:
        return current_index
    if normalized == "n":
        return min(current_index + 1, page_count - 1)
    if normalized == "p":
        return max(current_index - 1, 0)
    return current_index


def page_loop_available_keys(index: int, page_count: int) -> tuple[str, ...]:
    """Return page-loop keys available for the current page."""

    keys: list[str] = []
    if index < page_count - 1:
        keys.append("n")
    if index > 0:
        keys.append("p")
    if page_count > 0:
        keys.append("r")
    keys.append("q")
    return tuple(keys)


def run_artifact_page_loop(
    pages: Sequence[Path],
    *,
    read_key: Callable[[], str] | None = None,
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]]
    | None = None,
) -> _PageLoopResult:
    """Display rendered pages with ``kitten icat`` and a small key loop."""

    if not pages:
        return _PageLoopResult(returncode=1)

    read = read_key or _read_single_key
    run = run_command or _run_command
    index = 0
    while True:
        _clear_terminal(run)
        result = run(["kitten", "icat", str(pages[index])])
        if result.returncode != 0:
            return _PageLoopResult(returncode=result.returncode)
        _print_page_prompt(index=index, page_count=len(pages))
        available_keys = page_loop_available_keys(index, len(pages))
        while (key := read().lower()) not in available_keys:
            pass
        next_index = page_index_after_key(index, key, len(pages))
        print()
        if next_index is None:
            _clear_terminal(run)
            return _PageLoopResult()
        index = next_index


def _render_paginated_artifact(
    path: Path,
    mode: ArtifactViewMode,
    cache_dir: Path,
) -> ArtifactRenderResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if mode == "pdf":
        return convert_pdf_to_png_pages(path, cache_dir / "pdf_pages")

    pdf_path = cache_dir / f"{path.stem or 'artifact'}.pdf"
    rendered = render_markdown_pdf(path, pdf_path)
    if rendered is None:
        return ArtifactRenderResult(
            (),
            (
                ArtifactViewerWarning(
                    "markdown_render_failed",
                    "Markdown PDF rendering failed",
                ),
            ),
        )
    return convert_pdf_to_png_pages(rendered, cache_dir / "markdown_pages")


def _collect_pdftoppm_pages(prefix: Path) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(prefix.name)}-(\d+)\.png$")
    pages: list[tuple[int, Path]] = []
    for child in prefix.parent.glob(f"{prefix.name}-*.png"):
        match = pattern.match(child.name)
        if match is None:
            continue
        pages.append((int(match.group(1)), child))
    return [path for _, path in sorted(pages, key=lambda item: item[0])]


def _viewer_result_from_warnings(
    warnings: Sequence[ArtifactViewerWarning],
) -> ArtifactViewerResult:
    return ArtifactViewerResult(
        False,
        warning=warnings[0].message if warnings else None,
        warnings=tuple(warnings),
    )


def _artifact_viewer_module_command(
    path: str | Path,
    *,
    kind: str | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
    ]
    if kind is not None:
        command.extend(["--kind", str(kind)])
    command.append(str(Path(path).expanduser()))
    return command


def _run_command(cmd: Sequence[str]) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(list(cmd), check=False)


def _clear_terminal(
    run_command: Callable[[Sequence[str]], subprocess.CompletedProcess[Any]],
) -> None:
    run_command(["clear"])


def _print_page_prompt(*, index: int, page_count: int) -> None:
    labels = {
        "n": "n: next",
        "p": "p: previous",
        "r": "r: refresh",
        "q": "q: quit",
    }
    actions = "  ".join(
        labels[key] for key in page_loop_available_keys(index, page_count)
    )
    prompt = f"Page {index + 1}/{page_count}  {actions}"
    print(f"\n{prompt}", end="", flush=True)


def _read_single_key() -> str:
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return os.read(fd, 1).decode(errors="ignore")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _parse_viewer_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m sase.ace.tui.graphics.viewer",
        description="Open a SASE artifact in the terminal artifact viewer.",
    )
    parser.add_argument("path", help="Artifact file path to view")
    parser.add_argument(
        "-k",
        "--kind",
        default=None,
        help="Artifact kind used to choose the viewer mode",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the artifact viewer module entry point."""

    args = _parse_viewer_args(argv)
    result = view_artifact_file(args.path, kind=args.kind)
    if result.ok:
        return 0
    if result.warning is not None:
        print(result.warning, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
