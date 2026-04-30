"""Markdown-to-PDF rendering helpers for generated agent attachments."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

SUPPORTED_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
PDF_ENGINES = ("wkhtmltopdf", "xelatex", "pdflatex")
DEFAULT_PANDOC_TIMEOUT_SECONDS = 120


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
