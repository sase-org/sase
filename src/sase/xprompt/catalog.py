"""Build a beautifully-formatted PDF catalog of every visible xprompt.

Public surface: :func:`build_xprompts_catalog`.
"""

from __future__ import annotations

import hashlib
import importlib.resources
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sase.xprompt.loader import (
    get_all_xprompts,
    get_known_project_workspaces,
    get_sase_package_xprompts_dir,
    load_project_local_xprompts,
)
from sase.xprompt.models import UNSET, InputArg, XPrompt

log = logging.getLogger(__name__)


MAX_CONTENT_LINES = 40


class PdfEngineUnavailable(RuntimeError):
    """Raised when no HTML-capable PDF engine is available on PATH."""


class NoXpromptsFound(RuntimeError):
    """Raised when there are no xprompts to include in the catalog."""


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class CatalogStats:
    """Summary statistics for the xprompt catalog."""

    total: int
    by_source: dict[str, int]
    by_project: dict[str, int]
    by_tag: dict[str, int]
    with_description: int
    with_inputs: int
    skills: int
    generated_at: datetime


# pyvision: public_api_methods.txt
@dataclass(frozen=True)
class CatalogArtifact:
    """Result of building the xprompt catalog."""

    pdf_path: Path
    stats: CatalogStats


@dataclass
class _CatalogEntry:
    """Internal representation of an xprompt for rendering."""

    xprompt: XPrompt
    bucket: str  # built-in / project / config / plugin / memory
    project: str | None  # set when bucket == "project"


@dataclass
class _CatalogDocument:
    """In-memory model consumed by the HTML renderer."""

    entries_by_bucket: dict[str, list[_CatalogEntry]]
    stats: CatalogStats
    sections: list[tuple[str, list[tuple[str | None, list[_CatalogEntry]]]]] = field(
        default_factory=list
    )


SOURCE_BUCKETS = ("built-in", "project", "config", "plugin", "memory")
SOURCE_BUCKET_LABELS = {
    "built-in": "Built-in",
    "project": "Project",
    "config": "Config",
    "plugin": "Plugin",
    "memory": "Memory (auto)",
}


def build_xprompts_catalog(output_dir: Path | None = None) -> CatalogArtifact:
    """Gather every xprompt, compute stats, render a beautiful PDF.

    The PDF path is ``<output_dir>/xprompts_catalog_<YYYY-MM-DD>.pdf``.  Falls
    back to a tempdir when *output_dir* is ``None``.

    Raises:
        NoXpromptsFound: When the catalog would contain zero xprompts.
        PdfEngineUnavailable: When neither ``wkhtmltopdf`` nor ``pandoc`` is
            available on ``PATH``.
    """
    entries = _gather_entries()
    if not entries:
        raise NoXpromptsFound("no xprompts visible to the sase runtime")

    stats = _compute_stats(entries)
    document = _build_document(entries, stats)
    html = _render_html(document)

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="sase_xprompts_catalog_"))
    output_dir.mkdir(parents=True, exist_ok=True)
    date_suffix = stats.generated_at.strftime("%Y-%m-%d")
    pdf_path = output_dir / f"xprompts_catalog_{date_suffix}.pdf"

    _render_pdf(html, pdf_path)
    return CatalogArtifact(pdf_path=pdf_path, stats=stats)


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------


def _gather_entries() -> list[_CatalogEntry]:
    """Collect all xprompts from every source, classified and de-duplicated."""
    seen: dict[tuple[str, str], _CatalogEntry] = {}

    for xp in get_all_xprompts().values():
        entry = _classify(xp, project=None)
        seen[(xp.source_path or "", xp.name)] = entry

    for project, workspace in get_known_project_workspaces().items():
        try:
            project_xprompts = load_project_local_xprompts(workspace, project)
        except Exception:
            log.debug(
                "Failed to load project-local xprompts for %s",
                project,
                exc_info=True,
            )
            continue
        for xp in project_xprompts.values():
            key = (xp.source_path or "", xp.name)
            if key in seen:
                continue
            seen[key] = _classify(xp, project=project)

    return sorted(
        seen.values(), key=lambda e: (e.bucket, e.project or "", e.xprompt.name)
    )


def _classify(xp: XPrompt, project: str | None) -> _CatalogEntry:
    """Classify an xprompt into a source bucket."""
    source = xp.source_path or ""

    if source.startswith("plugin:"):
        return _CatalogEntry(xp, bucket="plugin", project=None)

    if source == "config" or source.startswith("config:"):
        return _CatalogEntry(xp, bucket="config", project=None)

    source_path = Path(source) if source else None

    try:
        package_dir = get_sase_package_xprompts_dir()
    except Exception:
        package_dir = None

    if source_path is not None and package_dir is not None:
        try:
            source_path.resolve().relative_to(package_dir.resolve())
            return _CatalogEntry(xp, bucket="built-in", project=None)
        except (ValueError, OSError):
            pass

    if source_path is not None and "memory/long" in source_path.as_posix():
        return _CatalogEntry(xp, bucket="memory", project=None)

    if project is not None:
        return _CatalogEntry(xp, bucket="project", project=project)

    workspaces = get_known_project_workspaces()
    if source_path is not None:
        for project_name, ws in workspaces.items():
            try:
                source_path.resolve().relative_to(ws.resolve())
                return _CatalogEntry(xp, bucket="project", project=project_name)
            except (ValueError, OSError):
                continue

    config_dir = Path.home() / ".config" / "sase"
    if source_path is not None:
        try:
            source_path.resolve().relative_to(config_dir.resolve())
            return _CatalogEntry(xp, bucket="config", project=None)
        except (ValueError, OSError):
            pass

    # Unknown source → treat as config (user-scoped config-like).
    return _CatalogEntry(xp, bucket="config", project=None)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def _compute_stats(entries: list[_CatalogEntry]) -> CatalogStats:
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


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------


def _build_document(
    entries: list[_CatalogEntry], stats: CatalogStats
) -> _CatalogDocument:
    by_bucket: dict[str, list[_CatalogEntry]] = {b: [] for b in SOURCE_BUCKETS}
    for entry in entries:
        by_bucket.setdefault(entry.bucket, []).append(entry)

    sections: list[tuple[str, list[tuple[str | None, list[_CatalogEntry]]]]] = []
    for bucket in SOURCE_BUCKETS:
        bucket_entries = by_bucket.get(bucket, [])
        if not bucket_entries:
            continue

        groups: dict[str | None, list[_CatalogEntry]] = {}
        for entry in bucket_entries:
            groups.setdefault(entry.project, []).append(entry)

        for key in groups:
            groups[key].sort(key=lambda e: e.xprompt.name.lower())

        sorted_groups = sorted(groups.items(), key=lambda kv: kv[0] or "")
        sections.append((bucket, sorted_groups))

    return _CatalogDocument(
        entries_by_bucket=by_bucket,
        stats=stats,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _render_html(document: _CatalogDocument) -> str:
    """Render the catalog to HTML using the Jinja2 template."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(str(importlib.resources.files("sase.xprompt").joinpath(".")))
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["tag_color_class"] = _tag_color_class
    env.filters["truncate_content"] = _truncate_content
    env.filters["format_inputs"] = _format_inputs
    env.filters["bar_width"] = _bar_width
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


def _tag_color_class(tag: str) -> str:
    """Deterministic pill colour class for a tag (4-way cycle)."""
    digest = hashlib.md5(tag.encode("utf-8")).hexdigest()
    bucket = int(digest[:2], 16) % 4
    return f"pill-color-{bucket}"


def _truncate_content(content: str, source_path: str | None = None) -> dict:
    """Return dict with 'text' and optional 'elided' note for a card body."""
    lines = content.splitlines()
    if len(lines) <= MAX_CONTENT_LINES:
        return {"text": content, "elided": None}
    head = "\n".join(lines[:MAX_CONTENT_LINES])
    remaining = len(lines) - MAX_CONTENT_LINES
    note = f"… ({remaining} more lines"
    if source_path:
        note += f" — see {source_path}"
    note += ")"
    return {"text": head, "elided": note}


def _format_inputs(inputs: list[InputArg]) -> str:
    """Render an input signature like ``(plan_file: path, notes?)``."""
    if not inputs:
        return ""
    parts: list[str] = []
    for inp in inputs:
        if inp.is_step_input:
            continue
        required = inp.default is UNSET
        suffix = "" if required else "?"
        parts.append(f"{inp.name}{suffix}: {inp.type.value}")
    if not parts:
        return ""
    return "(" + ", ".join(parts) + ")"


def _bar_width(count: int, maximum: int) -> int:
    """Return the % width of a bar chart segment."""
    if maximum <= 0:
        return 0
    return max(2, int(round(count * 100 / maximum)))


# ---------------------------------------------------------------------------
# PDF rendering
# ---------------------------------------------------------------------------


def _render_pdf(html: str, pdf_path: Path) -> None:
    """Convert *html* to a PDF at *pdf_path*.

    Prefers ``wkhtmltopdf`` (direct HTML → PDF), falls back to ``pandoc``.
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
            cmd = [
                pandoc,
                str(html_path),
                "-o",
                str(pdf_path),
                "--pdf-engine=wkhtmltopdf"
                if shutil.which("wkhtmltopdf")
                else "--pdf-engine=xelatex",
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
