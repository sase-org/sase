"""Markdown-to-PDF rendering helpers for generated agent attachments."""

from __future__ import annotations

from collections.abc import Iterable
import json
import logging
import re
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from sase.attachments._markdown_pdf_properties import (
    escape_markdown_text as _escape_markdown_text,
    plain_text_lines as _plain_text_lines,
    preprocess_markdown_source as _preprocess_markdown_source_impl,
    properties_card_markup as _properties_card_markup,
)
from sase.attachments._markdown_pdf_rendering import (
    DEFAULT_PANDOC_TIMEOUT_SECONDS,
    MAX_MARKDOWN_PDF_ATTACHMENTS,
    MOBILE_MARKDOWN_PDF_PROFILE,
    PDF_ENGINES,
    SUPPORTED_MARKDOWN_EXTENSIONS,
    MarkdownPdfProfile,
    MarkdownPdfProgressCallback,
    MarkdownPdfProgressEvent,
    MarkdownPdfRecord,
    css_for_profile as _css_for_profile,
    css_path_for_profile as _css_path_for_profile,
    default_markdown_pdf_css_path as _default_markdown_pdf_css_path,
    find_available_engines as _find_available_engines,
    launch_preview_css_path as _launch_preview_css_path,
    pandoc_cmd as _pandoc_cmd,
    sase_syntax_definition_path as _sase_syntax_definition_path,
    temporary_pdf_path as _temporary_pdf_path,
)

log = logging.getLogger(__name__)


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


def _preprocess_markdown_source(
    source: Path,
    directory: Path,
    *,
    include_properties: bool,
) -> tuple[Path, str, Path | None]:
    """Replace YAML frontmatter with a rendered Properties card when enabled."""
    return _preprocess_markdown_source_impl(
        source,
        directory,
        include_properties=include_properties,
        properties_card_markup=_properties_card_markup,
    )


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
