"""Pandoc configuration and low-level Markdown PDF rendering helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import tempfile

SUPPORTED_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
MAX_MARKDOWN_PDF_ATTACHMENTS = 10
PDF_ENGINES = ("wkhtmltopdf", "xelatex", "pdflatex")
DEFAULT_PANDOC_TIMEOUT_SECONDS = 120
_PDF_PAGE_WIDTH = "4.25in"
_PDF_PAGE_HEIGHT = "7in"
_PDF_MARGIN = "0.22in"
_PDF_BODY_FONT_SIZE = "12pt"
_PDF_CSS_FONT_SIZE = "16px"
_PDF_LINE_STRETCH = "1.32"
_DEFAULT_CSS_FILENAME = "markdown_pdf.css"
_LAUNCH_PREVIEW_CSS_FILENAME = "launch_preview.css"
_SASE_SYNTAX_DEFINITION_FILENAME = "sase.xml"


@dataclass(frozen=True)
class MarkdownPdfProfile:
    """Page and typography settings for Markdown PDF rendering."""

    page_width: str
    page_height: str
    margin: str
    css_font_size: str
    latex_font_size: str
    line_stretch: str = _PDF_LINE_STRETCH


MOBILE_MARKDOWN_PDF_PROFILE = MarkdownPdfProfile(
    page_width=_PDF_PAGE_WIDTH,
    page_height=_PDF_PAGE_HEIGHT,
    margin=_PDF_MARGIN,
    css_font_size=_PDF_CSS_FONT_SIZE,
    latex_font_size=_PDF_BODY_FONT_SIZE,
)


@dataclass(frozen=True)
class MarkdownPdfRecord:
    """Source-to-artifact mapping for a generated Markdown PDF."""

    source_path: str
    pdf_path: str


@dataclass(frozen=True)
class MarkdownPdfProgressEvent:
    """Progress update emitted while rendering Markdown PDFs."""

    stage: str
    source_path: str | None = None
    pdf_path: str | None = None
    engine: str | None = None
    index: int | None = None
    total: int | None = None
    generated: int | None = None
    skipped: int | None = None
    reason: str | None = None


MarkdownPdfProgressCallback = Callable[[MarkdownPdfProgressEvent], None]


def find_available_engines() -> list[str]:
    """Return installed PDF engines in preferred order."""
    return [engine for engine in PDF_ENGINES if shutil.which(engine)]


def pandoc_cmd(
    pandoc: str,
    source: Path,
    dest: Path,
    engine: str,
    css_path: Path | None,
    profile: MarkdownPdfProfile = MOBILE_MARKDOWN_PDF_PROFILE,
    *,
    title: str,
    syntax_definitions: Iterable[Path] = (),
    include_auto_title: bool = True,
    resource_paths: Iterable[Path] = (),
) -> list[str]:
    """Build a conservative pandoc command for Markdown-to-PDF conversion."""
    cmd = [
        pandoc,
        str(_absolute_path(source)),
        "-o",
        str(_absolute_path(dest)),
        f"--pdf-engine={engine}",
        "--highlight-style=tango",
    ]
    resource_path = _resource_path_argument(resource_paths)
    if resource_path is not None:
        cmd.append(f"--resource-path={resource_path}")
    for syntax_definition in syntax_definitions:
        cmd.append(f"--syntax-definition={_absolute_path(syntax_definition)}")
    if engine == "wkhtmltopdf":
        css = _absolute_path(css_path) if css_path is not None else None
        if css is not None and css.is_file():
            cmd.append(f"--css={css}")
        cmd += [
            "--pdf-engine-opt=--page-width",
            f"--pdf-engine-opt={profile.page_width}",
            "--pdf-engine-opt=--page-height",
            f"--pdf-engine-opt={profile.page_height}",
            "--pdf-engine-opt=--margin-top",
            f"--pdf-engine-opt={profile.margin}",
            "--pdf-engine-opt=--margin-right",
            f"--pdf-engine-opt={profile.margin}",
            "--pdf-engine-opt=--margin-bottom",
            f"--pdf-engine-opt={profile.margin}",
            "--pdf-engine-opt=--margin-left",
            f"--pdf-engine-opt={profile.margin}",
        ]
        if include_auto_title:
            cmd += ["--metadata", f"title={title}"]
    else:
        cmd += [
            "-V",
            (
                "geometry:"
                f"paperwidth={profile.page_width},"
                f"paperheight={profile.page_height},"
                f"margin={profile.margin}"
            ),
            "-V",
            f"fontsize={profile.latex_font_size}",
            "-V",
            f"linestretch={profile.line_stretch}",
        ]
    return cmd


def default_markdown_pdf_css_path() -> Path:
    return Path(__file__).with_name(_DEFAULT_CSS_FILENAME)


def launch_preview_css_path() -> Path:
    return Path(__file__).with_name(_LAUNCH_PREVIEW_CSS_FILENAME)


def sase_syntax_definition_path() -> Path:
    return Path(__file__).with_name(_SASE_SYNTAX_DEFINITION_FILENAME)


def css_path_for_profile(profile: MarkdownPdfProfile, directory: Path) -> Path:
    if profile == MOBILE_MARKDOWN_PDF_PROFILE:
        return default_markdown_pdf_css_path()

    with tempfile.NamedTemporaryFile(
        prefix=".markdown-pdf-profile.",
        suffix=".css",
        dir=directory,
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(css_for_profile(profile))
        return Path(tmp.name)


def css_for_profile(profile: MarkdownPdfProfile) -> str:
    css = default_markdown_pdf_css_path().read_text(encoding="utf-8")
    css = css.replace(
        f"size: {_PDF_PAGE_WIDTH} {_PDF_PAGE_HEIGHT};",
        f"size: {profile.page_width} {profile.page_height};",
        1,
    )
    css = css.replace(f"margin: {_PDF_MARGIN};", f"margin: {profile.margin};", 1)
    css = css.replace(
        f"font-size: {_PDF_CSS_FONT_SIZE};",
        f"font-size: {profile.css_font_size};",
        2,
    )
    css = css.replace(
        f"line-height: {_PDF_LINE_STRETCH};",
        f"line-height: {profile.line_stretch};",
        1,
    )
    return css


def temporary_pdf_path(dest: Path) -> Path:
    """Reserve a same-directory temporary PDF path for atomic replacement."""
    with tempfile.NamedTemporaryFile(
        prefix=f".{dest.stem}.",
        suffix=".pdf",
        dir=dest.parent,
        delete=False,
    ) as tmp:
        return Path(tmp.name)


def _absolute_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _resource_path_argument(resource_paths: Iterable[Path]) -> str | None:
    resolved: list[str] = []
    seen: set[str] = set()
    for path in resource_paths:
        value = str(_absolute_path(path))
        if value in seen:
            continue
        seen.add(value)
        resolved.append(value)
    if not resolved:
        return None
    return os.pathsep.join(resolved)
