"""Statistics, HTML rendering, and PDF rendering for xprompt catalogs."""

from __future__ import annotations

import importlib.resources
import logging
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from ._catalog_format import (
    bar_width,
    format_inputs,
    tag_color_class,
    truncate_content,
)
from ._catalog_models import (
    SOURCE_BUCKET_LABELS,
    SOURCE_BUCKETS,
    CatalogArtifact,
    CatalogDocument,
    CatalogEntry,
    CatalogStats,
    NoXpromptsFound,
    PdfEngineUnavailable,
)
from ._catalog_sources import gather_entries

log = logging.getLogger(__name__)


def build_xprompts_catalog(output_dir: Path | None = None) -> CatalogArtifact:
    """Gather every xprompt, compute stats, render a PDF.

    The PDF path is ``<output_dir>/xprompts_catalog_<YYYY-MM-DD>.pdf``. Falls
    back to a tempdir when *output_dir* is ``None``.

    Raises:
        NoXpromptsFound: When the catalog would contain zero xprompts.
        PdfEngineUnavailable: When neither ``wkhtmltopdf`` nor ``pandoc`` is
            available on ``PATH``.
    """
    entries = gather_entries()
    if not entries:
        raise NoXpromptsFound("no xprompts visible to the sase runtime")

    stats = compute_stats(entries)
    document = build_document(entries, stats)
    html = render_html(document)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="sase_xprompts_catalog_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    date_suffix = stats.generated_at.strftime("%Y-%m-%d")
    pdf_path = output_dir / f"xprompts_catalog_{date_suffix}.pdf"

    render_pdf(html, pdf_path)
    return CatalogArtifact(pdf_path=pdf_path, stats=stats)


def compute_stats(entries: list[CatalogEntry]) -> CatalogStats:
    by_source: dict[str, int] = dict.fromkeys(SOURCE_BUCKETS, 0)
    by_project: dict[str, int] = {}
    by_tag: dict[str, int] = {}
    with_description = 0
    with_inputs = 0
    skills = 0

    for entry in entries:
        by_source[entry.bucket] = by_source.get(entry.bucket, 0) + 1
        if entry.project:
            by_project[entry.project] = by_project.get(entry.project, 0) + 1
        for tag in entry.xprompt.tags:
            by_tag[tag.value] = by_tag.get(tag.value, 0) + 1
        if entry.xprompt.description:
            with_description += 1
        if entry.xprompt.inputs:
            with_inputs += 1
        if entry.xprompt.skill:
            skills += 1

    sorted_tags = dict(sorted(by_tag.items(), key=lambda kv: (-kv[1], kv[0])))
    sorted_projects = dict(sorted(by_project.items(), key=lambda kv: kv[0]))

    return CatalogStats(
        total=len(entries),
        by_source=by_source,
        by_project=sorted_projects,
        by_tag=sorted_tags,
        with_description=with_description,
        with_inputs=with_inputs,
        skills=skills,
        generated_at=datetime.now(UTC),
    )


def build_document(entries: list[CatalogEntry], stats: CatalogStats) -> CatalogDocument:
    by_bucket: dict[str, list[CatalogEntry]] = {b: [] for b in SOURCE_BUCKETS}
    for entry in entries:
        by_bucket.setdefault(entry.bucket, []).append(entry)

    sections: list[tuple[str, list[tuple[str | None, list[CatalogEntry]]]]] = []
    for bucket in SOURCE_BUCKETS:
        bucket_entries = by_bucket.get(bucket, [])
        if not bucket_entries:
            continue

        groups: dict[str | None, list[CatalogEntry]] = {}
        for entry in bucket_entries:
            groups.setdefault(entry.project, []).append(entry)

        for key in groups:
            groups[key].sort(key=lambda e: e.xprompt.name.lower())

        sorted_groups = sorted(groups.items(), key=lambda kv: kv[0] or "")
        sections.append((bucket, sorted_groups))

    return CatalogDocument(
        entries_by_bucket=by_bucket,
        stats=stats,
        sections=sections,
    )


def render_html(document: CatalogDocument) -> str:
    """Render the catalog to HTML using the Jinja2 template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(str(importlib.resources.files("sase.xprompt").joinpath(".")))
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["tag_color_class"] = tag_color_class
    env.filters["truncate_content"] = truncate_content
    env.filters["format_inputs"] = format_inputs
    env.filters["bar_width"] = bar_width
    env.filters["bucket_label"] = lambda b: SOURCE_BUCKET_LABELS.get(b, b)

    css_path = template_dir / "catalog_style.css"
    css_text = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    template = env.get_template("catalog_template.html.j2")
    return template.render(
        document=document,
        stats=document.stats,
        sections=document.sections,
        css_text=css_text,
        generated_date=document.stats.generated_at.strftime("%Y-%m-%d"),
    )


def render_pdf(html: str, pdf_path: Path) -> None:
    """Convert *html* to a PDF at *pdf_path*.

    Prefers ``wkhtmltopdf`` (direct HTML -> PDF), falls back to ``pandoc``.
    """
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html)
        html_path = Path(tmp.name)

    try:
        wkhtmltopdf = shutil.which("wkhtmltopdf")
        if wkhtmltopdf:
            cmd = [
                wkhtmltopdf,
                "--quiet",
                "--enable-local-file-access",
                "--print-media-type",
                "--margin-top",
                "18mm",
                "--margin-bottom",
                "18mm",
                "--margin-left",
                "20mm",
                "--margin-right",
                "20mm",
                str(html_path),
                str(pdf_path),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return
            except subprocess.CalledProcessError as exc:
                log.warning("wkhtmltopdf failed (%s); attempting pandoc fallback", exc)

        pandoc = shutil.which("pandoc")
        if pandoc:
            pdf_engine = (
                "--pdf-engine=wkhtmltopdf"
                if shutil.which("wkhtmltopdf")
                else "--pdf-engine=xelatex"
            )
            cmd = [
                pandoc,
                str(html_path),
                "-o",
                str(pdf_path),
                pdf_engine,
                "--metadata",
                "title=xprompts Catalog",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
                return
            except subprocess.CalledProcessError as exc:
                raise PdfEngineUnavailable(
                    f"pandoc failed to render PDF: {exc.stderr.decode(errors='replace')}"
                ) from exc

        raise PdfEngineUnavailable(
            "No PDF engine available. Install wkhtmltopdf or pandoc."
        )
    finally:
        try:
            html_path.unlink()
        except OSError:
            pass


_compute_stats = compute_stats
_build_document = build_document
_render_html = render_html
_render_pdf = render_pdf
