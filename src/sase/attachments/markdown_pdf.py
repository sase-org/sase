"""Markdown-to-PDF rendering helpers for generated agent attachments."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
MAX_MARKDOWN_PDF_ATTACHMENTS = 10
PDF_ENGINES = ("wkhtmltopdf", "xelatex", "pdflatex")
DEFAULT_PANDOC_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class MarkdownPdfRecord:
    """Source-to-artifact mapping for a generated Markdown PDF."""

    source_path: str
    pdf_path: str


def render_markdown_pdf_attachments(
    source_paths: Iterable[str],
    *,
    workspace_dir: str | Path,
    artifacts_dir: str | Path,
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

    for source_str in source_paths:
        source = Path(source_str).expanduser()
        dest = _unique_pdf_destination(
            pdf_dir / _pdf_filename_for_source(source, workspace),
            used_destinations,
        )
        used_destinations.add(dest)
        rendered = render_markdown_pdf(source, dest)
        if rendered is None:
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
    return [record.pdf_path for record in records]


def render_markdown_pdf(
    source_path: str | Path,
    dest_path: str | Path,
    *,
    timeout: int = DEFAULT_PANDOC_TIMEOUT_SECONDS,
    css_path: str | Path | None = None,
) -> Path | None:
    """Render Markdown at *source_path* to the caller-provided PDF path.

    Returns the destination path on success. Missing tools, unsupported source
    paths, missing source files, and conversion failures return ``None``. Failed
    attempts never leave a partial PDF at *dest_path*.
    """
    source = Path(source_path).expanduser()
    dest = Path(dest_path).expanduser()

    if source.suffix.lower() not in SUPPORTED_MARKDOWN_EXTENSIONS:
        return None
    if dest.suffix.lower() != ".pdf":
        return None
    if not source.is_file():
        log.warning("Cannot render missing Markdown file to PDF: %s", source)
        return None

    pandoc = shutil.which("pandoc")
    if not pandoc:
        log.warning("pandoc not found; cannot render Markdown PDF for %s", source)
        return None

    engines = _find_available_engines()
    if not engines:
        log.warning("No PDF engine found; cannot render Markdown PDF for %s", source)
        return None

    dest.parent.mkdir(parents=True, exist_ok=True)
    css = Path(css_path).expanduser() if css_path is not None else None

    last_error: BaseException | None = None
    for engine in engines:
        tmp_path = _temporary_pdf_path(dest)
        cmd = _pandoc_cmd(pandoc, source, tmp_path, engine, css)
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
            tmp_path.replace(dest)
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

    log.warning("All PDF engines failed for %s (last: %s)", source, last_error)
    dest.unlink(missing_ok=True)
    return None


def _find_available_engines() -> list[str]:
    """Return installed PDF engines in preferred order."""
    return [engine for engine in PDF_ENGINES if shutil.which(engine)]


def _pandoc_cmd(
    pandoc: str,
    source: Path,
    dest: Path,
    engine: str,
    css_path: Path | None,
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
        cmd += ["--metadata", f"title={source.stem}"]
    else:
        cmd += ["-V", "geometry:margin=1in"]
    return cmd


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
