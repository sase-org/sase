"""Markdown-to-PDF rendering helpers for generated agent attachments."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from html import escape
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.plan_properties import (
    ordered_plan_property_items,
    plan_property_label,
    render_plan_value_lines,
)

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
    syntax_definitions: Iterable[str | Path] = (),
    include_auto_title: bool = True,
    include_properties: bool = True,
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
    syntax_definition_paths = tuple(
        Path(path).expanduser() for path in syntax_definitions
    )
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

    render_source = source
    document_title = source.stem
    preprocessed_source_path: Path | None = None
    last_error: BaseException | None = None
    try:
        try:
            (
                render_source,
                document_title,
                preprocessed_source_path,
            ) = _preprocess_markdown_source(
                source,
                dest.parent,
                include_properties=include_properties,
            )
        except Exception:
            log.debug(
                "Could not add frontmatter properties while rendering %s",
                source,
                exc_info=True,
            )

        for engine in engines:
            tmp_path = _temporary_pdf_path(dest)
            cmd = _pandoc_cmd(
                pandoc,
                render_source,
                tmp_path,
                engine,
                css,
                profile,
                title=document_title,
                syntax_definitions=syntax_definition_paths,
                include_auto_title=include_auto_title,
            )
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
        if preprocessed_source_path is not None:
            preprocessed_source_path.unlink(missing_ok=True)
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


def render_launch_preview_pdf(
    source_path: str | Path,
    dest_path: str | Path,
    *,
    timeout: int = DEFAULT_PANDOC_TIMEOUT_SECONDS,
    progress: MarkdownPdfProgressCallback | None = None,
) -> Path | None:
    """Render a launch-preview Markdown file with SASE prompt highlighting.

    The highlighted pass is additive. If the syntax definition, CSS, or a PDF
    engine rejects the dedicated render, fall back to the generic Markdown PDF
    renderer so the complete prompt remains deliverable.
    """
    source = Path(source_path).expanduser()
    dest = Path(dest_path).expanduser()
    rendered = render_markdown_pdf(
        source,
        dest,
        timeout=timeout,
        css_path=_launch_preview_css_path(),
        syntax_definitions=[_sase_syntax_definition_path()],
        include_auto_title=False,
        include_properties=False,
        progress=progress,
    )
    if rendered is not None:
        return rendered

    log.warning(
        "Falling back to generic Markdown PDF rendering for launch preview: %s",
        source,
    )
    return render_markdown_pdf(
        source,
        dest,
        timeout=timeout,
        include_properties=False,
        progress=progress,
    )


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
    *,
    title: str,
    syntax_definitions: Iterable[Path] = (),
    include_auto_title: bool = True,
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
    for syntax_definition in syntax_definitions:
        cmd.append(f"--syntax-definition={syntax_definition}")
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


def _preprocess_markdown_source(
    source: Path,
    directory: Path,
    *,
    include_properties: bool,
) -> tuple[Path, str, Path | None]:
    """Replace YAML frontmatter with a rendered Properties card when enabled."""
    title = source.stem
    if not include_properties:
        return source, title, None

    content = source.read_text(encoding="utf-8")
    frontmatter, body, had_frontmatter = parse_frontmatter(content)
    if not had_frontmatter or not frontmatter:
        return source, title, None

    if "title" in frontmatter:
        title = str(frontmatter["title"])
    card = _properties_card_markup(frontmatter)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{source.stem}.properties.",
            suffix=source.suffix,
            dir=directory,
            mode="w",
            encoding="utf-8",
            delete=False,
        ) as tmp:
            temporary_path = Path(tmp.name)
            tmp.write(f"{card}\n\n{body}")
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path, title, temporary_path


def _properties_card_markup(frontmatter: Mapping[str, Any]) -> str:
    """Render a self-contained, HTML-safe frontmatter Properties card."""
    rows = [
        (plan_property_label(key), render_plan_value_lines(value))
        for key, value in ordered_plan_property_items(frontmatter)
    ]
    container_style = (
        "background:#f6f8fa;border:1px solid #d8dee4;border-radius:4px;"
        "box-sizing:border-box;margin:0 0 1em;overflow:hidden;padding:0;"
    )
    heading_style = (
        "background:#eef1f4;border-bottom:1px solid #d8dee4;color:#111827;"
        "font-size:0.95em;font-weight:700;letter-spacing:0.01em;"
        "padding:0.5em 0.65em;"
    )
    table_style = (
        "border:0;border-collapse:collapse;margin:0;table-layout:fixed;width:100%;"
    )
    label_style = (
        "border:0;color:#57606a;font-size:0.82em;font-weight:600;"
        "padding:0.42em 0.65em;text-align:left;vertical-align:top;width:28%;"
    )
    value_style = "border:0;color:#1f2328;padding:0.42em 0.65em;vertical-align:top;"
    line_style = "line-height:1.3;margin:0;white-space:pre-wrap;"
    row_style = "border-top:1px solid #d8dee4;break-inside:avoid;"

    html_markup = [
        (
            '<div class="sase-properties" aria-label="Properties" '
            f'style="{container_style}">'
        ),
        (
            '<div class="sase-properties__heading" '
            f'style="{heading_style}">Properties</div>'
        ),
        f'<table class="sase-properties__table" style="{table_style}">',
        "<tbody>",
    ]
    for label, value_lines in rows:
        html_markup.extend(
            [
                f'<tr class="sase-properties__row" style="{row_style}">',
                (
                    '<th class="sase-properties__label" scope="row" '
                    f'style="{label_style}">{escape(label, quote=True)}</th>'
                ),
                (f'<td class="sase-properties__value" style="{value_style}">'),
            ]
        )
        for line in value_lines:
            escaped_line = escape(line, quote=True) or "&#160;"
            html_markup.append(
                '<div class="sase-properties__value-line" '
                f'style="{line_style}">{escaped_line}</div>'
            )
        html_markup.extend(["</td>", "</tr>"])
    html_markup.extend(["</tbody>", "</table>", "</div>"])

    fallback_markup = [
        '::: {.sase-properties-fallback style="display:none;"}',
        "",
        "**Properties**",
        "",
    ]
    for label, value_lines in rows:
        fallback_markup.append(f"**{_escape_markdown_text(label)}:**  ")
        rendered_value = False
        for line in value_lines:
            for physical_line in _plain_text_lines(line):
                physical_line = physical_line.lstrip()
                if not physical_line:
                    continue
                fallback_markup.append(f"{_escape_markdown_text(physical_line)}  ")
                rendered_value = True
        if not rendered_value:
            fallback_markup.append("—  ")
        fallback_markup.append("")
    fallback_markup.append(":::")
    return "\n".join(
        [
            "```{=html}",
            *html_markup,
            "```",
            "",
            *fallback_markup,
        ]
    )


def _plain_text_lines(value: str) -> list[str]:
    """Split arbitrary property text into safe physical fallback lines."""
    return value.splitlines() or [""]


def _escape_markdown_text(value: str) -> str:
    """Escape arbitrary property text for the native Markdown fallback."""
    return re.sub(r"""([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])""", r"\\\1", value)


def _default_markdown_pdf_css_path() -> Path:
    return Path(__file__).with_name(_DEFAULT_CSS_FILENAME)


def _launch_preview_css_path() -> Path:
    return Path(__file__).with_name(_LAUNCH_PREVIEW_CSS_FILENAME)


def _sase_syntax_definition_path() -> Path:
    return Path(__file__).with_name(_SASE_SYNTAX_DEFINITION_FILENAME)


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
