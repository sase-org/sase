"""Markdown-to-PDF rendering helpers for generated agent attachments."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

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


def render_markdown_pdf_attachments(
    source_paths: Iterable[str],
    *,
    workspace_dir: str | Path,
    artifacts_dir: str | Path,
    progress: MarkdownPdfProgressCallback | None = None,
) -> list[str]:
    """Render Markdown sources into ``artifacts_dir/markdown_pdfs``.

    Returns successfully generated PDF paths in source order. Conversion is
    best-effort: unsupported/missing sources and render failures are skipped.
    A sidecar ``index.json`` is written only when at least one PDF is produced.
    """
    workspace = Path(workspace_dir).expanduser()
    pdf_dir = Path(artifacts_dir).expanduser() / "markdown_pdfs"
    records: list[MarkdownPdfRecord] = []
    used_destinations: set[Path] = set()
    sources = list(source_paths)
    total = len(sources)
    skipped = 0

    _emit_progress(
        progress,
        MarkdownPdfProgressEvent(
            stage="started",
            total=total,
            generated=0,
            skipped=0,
        ),
    )

    for index, source_str in enumerate(sources, start=1):
        source = Path(source_str).expanduser()
        dest = _unique_pdf_destination(
            pdf_dir / _pdf_filename_for_source(source, workspace),
            used_destinations,
        )
        used_destinations.add(dest)

        def _source_progress(
            event: MarkdownPdfProgressEvent,
            *,
            current_index: int = index,
        ) -> None:
            enriched = MarkdownPdfProgressEvent(
                stage=event.stage,
                source_path=event.source_path,
                pdf_path=event.pdf_path,
                engine=event.engine,
                index=current_index if event.index is None else event.index,
                total=total if event.total is None else event.total,
                generated=event.generated,
                skipped=event.skipped,
                reason=event.reason,
            )
            _emit_progress(progress, enriched)

        rendered = render_markdown_pdf(source, dest, progress=_source_progress)
        if rendered is None:
            skipped += 1
            continue
        record = MarkdownPdfRecord(
            source_path=str(source),
            pdf_path=str(rendered),
        )
        records.append(record)

    if records:
        index_path = pdf_dir / "index.json"
        index_path.write_text(
            json.dumps([asdict(record) for record in records], indent=2),
            encoding="utf-8",
        )
    _emit_progress(
        progress,
        MarkdownPdfProgressEvent(
            stage="completed",
            total=total,
            generated=len(records),
            skipped=skipped,
        ),
    )
    return [record.pdf_path for record in records]


def render_markdown_pdf(
    source_path: str | Path,
    dest_path: str | Path,
    *,
    timeout: int = DEFAULT_PANDOC_TIMEOUT_SECONDS,
    css_path: str | Path | None = None,
    profile: MarkdownPdfProfile = MOBILE_MARKDOWN_PDF_PROFILE,
    progress: MarkdownPdfProgressCallback | None = None,
) -> Path | None:
    """Render Markdown at *source_path* to the caller-provided PDF path.

    Returns the destination path on success. Missing tools, unsupported source
    paths, missing source files, and conversion failures return ``None``. Failed
    attempts never leave a partial PDF at *dest_path*.
    """
    source = Path(source_path).expanduser()
    dest = Path(dest_path).expanduser()
    _emit_progress(
        progress,
        MarkdownPdfProgressEvent(
            stage="source_started",
            source_path=str(source),
            pdf_path=str(dest),
        ),
    )

    if source.suffix.lower() not in SUPPORTED_MARKDOWN_EXTENSIONS:
        _emit_progress(
            progress,
            MarkdownPdfProgressEvent(
                stage="skipped",
                source_path=str(source),
                pdf_path=str(dest),
                reason="unsupported source",
            ),
        )
        return None
    if dest.suffix.lower() != ".pdf":
        _emit_progress(
            progress,
            MarkdownPdfProgressEvent(
                stage="skipped",
                source_path=str(source),
                pdf_path=str(dest),
                reason="destination is not a PDF",
            ),
        )
        return None
    if not source.is_file():
        log.warning("Cannot render missing Markdown file to PDF: %s", source)
        _emit_progress(
            progress,
            MarkdownPdfProgressEvent(
                stage="skipped",
                source_path=str(source),
                pdf_path=str(dest),
                reason="missing source",
            ),
        )
        return None

    pandoc = shutil.which("pandoc")
    if not pandoc:
        log.warning("pandoc not found; cannot render Markdown PDF for %s", source)
        _emit_progress(
            progress,
            MarkdownPdfProgressEvent(
                stage="skipped",
                source_path=str(source),
                pdf_path=str(dest),
                reason="pandoc not found",
            ),
        )
        return None

    engines = _find_available_engines()
    if not engines:
        log.warning("No PDF engine found; cannot render Markdown PDF for %s", source)
        _emit_progress(
            progress,
            MarkdownPdfProgressEvent(
                stage="skipped",
                source_path=str(source),
                pdf_path=str(dest),
                reason="no PDF engine found",
            ),
        )
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    generated_css_path: Path | None = None
    css = (
        Path(css_path).expanduser()
        if css_path is not None
        else _css_path_for_profile(profile, dest.parent)
    )
    if css_path is None and profile != MOBILE_MARKDOWN_PDF_PROFILE:
        generated_css_path = css

    last_error: BaseException | None = None
    try:
        for engine in engines:
            tmp_path = _temporary_pdf_path(dest)
            cmd = _pandoc_cmd(pandoc, source, tmp_path, engine, css, profile)
            _emit_progress(
                progress,
                MarkdownPdfProgressEvent(
                    stage="engine_started",
                    source_path=str(source),
                    pdf_path=str(dest),
                    engine=engine,
                ),
            )
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
                tmp_path.replace(dest)
                _emit_progress(
                    progress,
                    MarkdownPdfProgressEvent(
                        stage="source_succeeded",
                        source_path=str(source),
                        pdf_path=str(dest),
                        engine=engine,
                    ),
                )
                return dest
            except subprocess.TimeoutExpired as exc:
                log.warning(
                    "pandoc timed out with engine %s while rendering %s",
                    engine,
                    source,
                )
                last_error = exc
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                log.debug(
                    "pandoc failed with engine %s while rendering %s: %s",
                    engine,
                    source,
                    exc,
                )
                last_error = exc
            finally:
                tmp_path.unlink(missing_ok=True)
    finally:
        if generated_css_path is not None:
            generated_css_path.unlink(missing_ok=True)

    log.warning("All PDF engines failed for %s (last: %s)", source, last_error)
    dest.unlink(missing_ok=True)
    _emit_progress(
        progress,
        MarkdownPdfProgressEvent(
            stage="source_failed",
            source_path=str(source),
            pdf_path=str(dest),
            reason="all PDF engines failed",
        ),
    )
    return None


def _emit_progress(
    progress: MarkdownPdfProgressCallback | None,
    event: MarkdownPdfProgressEvent,
) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        log.debug("Markdown PDF progress callback failed", exc_info=True)


def _find_available_engines() -> list[str]:
    """Return installed PDF engines in preferred order."""
    return [engine for engine in PDF_ENGINES if shutil.which(engine)]


def _pandoc_cmd(
    pandoc: str,
    source: Path,
    dest: Path,
    engine: str,
    css_path: Path | None,
    profile: MarkdownPdfProfile = MOBILE_MARKDOWN_PDF_PROFILE,
) -> list[str]:
    """Build a conservative pandoc command for Markdown-to-PDF conversion."""
    cmd = [
        pandoc,
        str(source),
        "-o",
        str(dest),
        f"--pdf-engine={engine}",
        "--highlight-style=tango",
    ]
    if engine == "wkhtmltopdf":
        if css_path is not None and css_path.is_file():
            cmd.append(f"--css={css_path}")
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
        cmd += ["--metadata", f"title={source.stem}"]
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


def _default_markdown_pdf_css_path() -> Path:
    return Path(__file__).with_name(_DEFAULT_CSS_FILENAME)


def _css_path_for_profile(profile: MarkdownPdfProfile, directory: Path) -> Path:
    if profile == MOBILE_MARKDOWN_PDF_PROFILE:
        return _default_markdown_pdf_css_path()

    with tempfile.NamedTemporaryFile(
        prefix=".markdown-pdf-profile.",
        suffix=".css",
        dir=directory,
        mode="w",
        encoding="utf-8",
        delete=False,
    ) as tmp:
        tmp.write(_css_for_profile(profile))
        return Path(tmp.name)


def _css_for_profile(profile: MarkdownPdfProfile) -> str:
    css = _default_markdown_pdf_css_path().read_text(encoding="utf-8")
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


def _temporary_pdf_path(dest: Path) -> Path:
    """Reserve a same-directory temporary PDF path for atomic replacement."""
    with tempfile.NamedTemporaryFile(
        prefix=f".{dest.stem}.",
        suffix=".pdf",
        dir=dest.parent,
        delete=False,
    ) as tmp:
        return Path(tmp.name)


def _pdf_filename_for_source(source: Path, workspace: Path) -> str:
    try:
        relative = source.resolve(strict=False).relative_to(
            workspace.resolve(strict=False)
        )
        parts = relative.parts
    except (OSError, ValueError):
        parts = (source.name,)
    safe_parts = [_sanitize_path_part(part) for part in parts if part]
    stem = "__".join(safe_parts) or "markdown"
    return f"{stem}.pdf"


def _sanitize_path_part(part: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip("._")
    return safe or "path"


def _unique_pdf_destination(dest: Path, used_destinations: set[Path]) -> Path:
    if dest not in used_destinations:
        return dest
    counter = 2
    while True:
        candidate = dest.with_name(f"{dest.stem}-{counter}{dest.suffix}")
        if candidate not in used_destinations:
            return candidate
        counter += 1
