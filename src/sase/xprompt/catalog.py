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
    get_sase_package_default_xprompts_dir,
    get_sase_package_xprompts_dir,
    load_project_local_xprompts,
)
from sase.xprompt.models import UNSET, InputArg, XPrompt

log = logging.getLogger(__name__)


MAX_CONTENT_LINES = 40
MAX_MOBILE_CONTENT_PREVIEW_CHARS = 800


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


@dataclass(frozen=True)
class StructuredCatalogEntry:
    """Mobile-safe structured xprompt catalog entry."""

    name: str
    display_label: str
    description: str | None
    source_bucket: str
    project: str | None
    tags: list[str]
    input_signature: str | None
    is_skill: bool
    content_preview: str | None
    source_path_display: str | None


@dataclass(frozen=True)
class StructuredCatalogStats:
    """Stats needed by the mobile xprompt catalog picker."""

    total_count: int
    project_count: int
    skill_count: int
    pdf_requested: bool


@dataclass(frozen=True)
class StructuredCatalogAttachment:
    """Safe metadata for an optional generated xprompt PDF catalog."""

    display_name: str
    content_type: str | None
    byte_size: int | None
    path_display: str | None
    generated: bool


@dataclass(frozen=True)
class StructuredCatalogSkipped:
    """Structured best-effort catalog skip/warning item."""

    target: str | None
    reason: str


@dataclass(frozen=True)
class StructuredCatalogProjection:
    """Pure structured xprompt catalog plus optional PDF metadata."""

    entries: list[StructuredCatalogEntry]
    stats: StructuredCatalogStats
    warnings: list[str]
    skipped: list[StructuredCatalogSkipped]
    catalog_attachment: StructuredCatalogAttachment | None


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


def build_structured_xprompts_catalog(
    *,
    project: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    include_pdf: bool = False,
    limit: int | None = None,
) -> StructuredCatalogProjection:
    """Return a mobile-safe structured xprompt catalog projection.

    This path intentionally gathers and filters xprompt metadata without
    requiring an HTML/PDF renderer. PDF generation is best-effort and only runs
    when explicitly requested.
    """
    filtered_entries = _filter_catalog_entries(
        _gather_entries(),
        project=project,
        source=source,
        tag=tag,
        query=query,
    )
    total_count = len(filtered_entries)
    entries = filtered_entries
    if limit is not None:
        entries = entries[:limit]

    structured_entries = [_structured_entry(entry) for entry in entries]
    warnings: list[str] = []
    skipped: list[StructuredCatalogSkipped] = []
    attachment: StructuredCatalogAttachment | None = None

    if include_pdf:
        try:
            artifact = build_xprompts_catalog()
        except NoXpromptsFound as exc:
            warnings.append("PDF catalog was not generated")
            skipped.append(
                StructuredCatalogSkipped(target="xprompt-catalog.pdf", reason=str(exc))
            )
        except PdfEngineUnavailable as exc:
            warnings.append("PDF catalog was not generated")
            skipped.append(
                StructuredCatalogSkipped(target="xprompt-catalog.pdf", reason=str(exc))
            )
        else:
            attachment = StructuredCatalogAttachment(
                display_name=artifact.pdf_path.name,
                content_type="application/pdf",
                byte_size=_safe_file_size(artifact.pdf_path),
                path_display=_safe_path_display(artifact.pdf_path),
                generated=True,
            )

    return StructuredCatalogProjection(
        entries=structured_entries,
        stats=StructuredCatalogStats(
            total_count=total_count,
            project_count=len(
                {entry.project for entry in filtered_entries if entry.project}
            ),
            skill_count=sum(1 for entry in filtered_entries if entry.xprompt.skill),
            pdf_requested=include_pdf,
        ),
        warnings=warnings,
        skipped=skipped,
        catalog_attachment=attachment,
    )


def _filter_catalog_entries(
    entries: list[_CatalogEntry],
    *,
    project: str | None,
    source: str | None,
    tag: str | None,
    query: str | None,
) -> list[_CatalogEntry]:
    normalized_query = query.casefold() if query else None
    filtered: list[_CatalogEntry] = []
    for entry in entries:
        if project is not None and entry.project not in (None, project):
            continue
        if source is not None and entry.bucket != source:
            continue
        tag_values = [tag.value for tag in entry.xprompt.tags]
        if tag is not None and tag not in tag_values:
            continue
        if normalized_query is not None and not _entry_matches_query(
            entry, tag_values, normalized_query
        ):
            continue
        filtered.append(entry)
    return filtered


def _entry_matches_query(
    entry: _CatalogEntry, tag_values: list[str], query: str
) -> bool:
    haystack = "\n".join(
        part
        for part in (
            entry.xprompt.name,
            entry.xprompt.description or "",
            entry.xprompt.content,
            " ".join(tag_values),
        )
        if part
    )
    return query in haystack.casefold()


def _structured_entry(entry: _CatalogEntry) -> StructuredCatalogEntry:
    input_signature = _format_inputs(entry.xprompt.inputs) or None
    return StructuredCatalogEntry(
        name=entry.xprompt.name,
        display_label=_display_label(entry.xprompt.name),
        description=entry.xprompt.description,
        source_bucket=entry.bucket,
        project=entry.project,
        tags=sorted(tag.value for tag in entry.xprompt.tags),
        input_signature=input_signature,
        is_skill=bool(entry.xprompt.skill),
        content_preview=_content_preview(entry.xprompt.content),
        source_path_display=_source_path_display(entry),
    )


def _display_label(name: str) -> str:
    label = name.replace("_", " ").replace("-", " ").strip()
    return label or name


def _content_preview(content: str) -> str | None:
    text = content.strip()
    if not text:
        return None
    if len(text) <= MAX_MOBILE_CONTENT_PREVIEW_CHARS:
        return text
    return text[:MAX_MOBILE_CONTENT_PREVIEW_CHARS].rstrip() + "..."


def _source_path_display(entry: _CatalogEntry) -> str | None:
    source = entry.xprompt.source_path
    if not source:
        return None
    if source == "config" or source.startswith(
        ("config:", "plugin:", "plugin_config:")
    ):
        return source

    path = Path(source)
    if not path.is_absolute():
        return source

    for project, workspace in get_known_project_workspaces().items():
        try:
            rel = path.resolve().relative_to(workspace.resolve())
        except (ValueError, OSError):
            continue
        if entry.project is None or project == entry.project:
            return rel.as_posix()

    for package_dir in _package_xprompt_dirs():
        try:
            rel = path.resolve().relative_to(package_dir.resolve())
        except (ValueError, OSError):
            continue
        return f"{package_dir.name}/{rel.as_posix()}"

    config_dir = Path.home() / ".config" / "sase"
    try:
        rel = path.resolve().relative_to(config_dir.resolve())
    except (ValueError, OSError):
        return None
    return f"~/.config/sase/{rel.as_posix()}"


def _safe_path_display(path: Path) -> str | None:
    try:
        resolved = path.resolve()
    except OSError:
        return None
    home = Path.home()
    try:
        rel = resolved.relative_to(home.resolve())
    except (ValueError, OSError):
        return None
    return f"~/{rel.as_posix()}"


def _safe_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


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

    if source_path is not None:
        for package_dir in _package_xprompt_dirs():
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


def _package_xprompt_dirs() -> list[Path]:
    package_dirs: list[Path] = []
    for get_package_dir in (
        get_sase_package_xprompts_dir,
        get_sase_package_default_xprompts_dir,
    ):
        try:
            package_dirs.append(get_package_dir())
        except Exception:
            pass
    return package_dirs


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
