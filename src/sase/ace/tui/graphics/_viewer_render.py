"""Rendering and dependency checks for the terminal artifact viewer."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from sase.attachments.markdown_pdf import (
    PDF_ENGINES,
    MarkdownPdfProfile,
    render_markdown_pdf,
)

from ._viewer_types import (
    ArtifactImageArea,
    ArtifactRenderResult,
    ArtifactViewerWarning,
    ArtifactViewMode,
)
from .images import is_supported_image_path

_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})
_MIN_ARTIFACT_PAGE_WIDTH_IN = 4.25
_MAX_ARTIFACT_PAGE_WIDTH_IN = 11.0
_MIN_ARTIFACT_PAGE_HEIGHT_IN = 3.0
_MAX_ARTIFACT_PAGE_HEIGHT_IN = 8.5
_ARTIFACT_PAGE_HEIGHT_PER_ROW_IN = 0.15
_ARTIFACT_PAGE_MARGIN_IN = 0.18
_MIN_ARTIFACT_PAGE_ASPECT = 0.7
_MAX_ARTIFACT_PAGE_ASPECT = 3.0


def render_artifact_pages(
    path: str | Path,
    *,
    kind: str | None = None,
    cache_dir: str | Path | None = None,
    image_area: ArtifactImageArea | None = None,
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
    return _render_paginated_artifact(
        expanded,
        mode,
        render_root,
        image_area=image_area,
    )


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


def _render_paginated_artifact(
    path: Path,
    mode: ArtifactViewMode,
    cache_dir: Path,
    *,
    image_area: ArtifactImageArea | None = None,
) -> ArtifactRenderResult:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if mode == "pdf":
        return convert_pdf_to_png_pages(path, cache_dir / "pdf_pages")

    pdf_path = cache_dir / f"{path.stem or 'artifact'}.pdf"
    profile = artifact_markdown_pdf_profile_for_image_area(image_area)
    rendered = (
        render_markdown_pdf(path, pdf_path, profile=profile)
        if profile is not None
        else render_markdown_pdf(path, pdf_path)
    )
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


def artifact_markdown_pdf_profile_for_image_area(
    image_area: ArtifactImageArea | None,
) -> MarkdownPdfProfile | None:
    """Return a pane-shaped Markdown profile for the artifact viewer."""

    if image_area is None or image_area.columns <= 0 or image_area.rows <= 0:
        return None

    aspect = _clamp(
        image_area.columns / image_area.rows,
        _MIN_ARTIFACT_PAGE_ASPECT,
        _MAX_ARTIFACT_PAGE_ASPECT,
    )
    height = _clamp(
        image_area.rows * _ARTIFACT_PAGE_HEIGHT_PER_ROW_IN,
        _MIN_ARTIFACT_PAGE_HEIGHT_IN,
        _MAX_ARTIFACT_PAGE_HEIGHT_IN,
    )
    width = height * aspect

    if width > _MAX_ARTIFACT_PAGE_WIDTH_IN:
        width = _MAX_ARTIFACT_PAGE_WIDTH_IN
        height = width / aspect
    elif width < _MIN_ARTIFACT_PAGE_WIDTH_IN:
        width = _MIN_ARTIFACT_PAGE_WIDTH_IN
        height = width / aspect

    height = _clamp(
        height,
        _MIN_ARTIFACT_PAGE_HEIGHT_IN,
        _MAX_ARTIFACT_PAGE_HEIGHT_IN,
    )

    return MarkdownPdfProfile(
        page_width=f"{width:.2f}in",
        page_height=f"{height:.2f}in",
        margin=f"{_ARTIFACT_PAGE_MARGIN_IN:.2f}in",
        css_font_size="16px",
        latex_font_size="12pt",
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _collect_pdftoppm_pages(prefix: Path) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(prefix.name)}-(\d+)\.png$")
    pages: list[tuple[int, Path]] = []
    for child in prefix.parent.glob(f"{prefix.name}-*.png"):
        match = pattern.match(child.name)
        if match is None:
            continue
        pages.append((int(match.group(1)), child))
    return [path for _, path in sorted(pages, key=lambda item: item[0])]
