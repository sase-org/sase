"""Build PDF and structured catalogs of visible xprompts.

Public surface:
- :func:`build_xprompts_catalog`
- :func:`build_structured_xprompts_catalog`
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sase.xprompt.loader import (
    get_all_workflows,
    get_all_xprompts,
    get_known_project_workspaces,
    get_sase_package_default_xprompts_dir,
    get_sase_package_xprompts_dir,
    load_project_local_xprompts,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow

from . import _catalog_sources as _sources
from ._catalog_format import (
    MAX_CONTENT_LINES,
    MAX_MOBILE_CONTENT_PREVIEW_CHARS,
    bar_width as _bar_width,
    format_inputs as _format_inputs,
    tag_color_class as _tag_color_class,
    truncate_content as _truncate_content,
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
    StructuredCatalogAttachment,
    StructuredCatalogEntry,
    StructuredCatalogInput,
    StructuredCatalogProjection,
    StructuredCatalogSkipped,
    StructuredCatalogSource,
    StructuredCatalogStats,
    _CatalogDocument,
    _CatalogEntry,
    _StructuredCatalogSource,
)
from ._catalog_render import (
    build_document as _build_document,
    compute_stats as _compute_stats,
    render_html as _render_html,
    render_pdf as _render_pdf,
)
from ._catalog_sources import (
    classify as _classify_impl,
    classify_workflow as _classify_workflow_impl,
    classify_xprompt_for_structured as _classify_xprompt_for_structured_impl,
    entry_source_path as _entry_source_path_impl,
    package_xprompt_dirs as _package_xprompt_dirs_impl,
)
from ._catalog_structured import (
    content_preview as _content_preview,
    default_display as _default_display,
    display_label as _display_label,
    filter_structured_catalog_entries as _filter_structured_catalog_entries,
    structured_entry as _structured_entry,
    structured_entry_matches_query as _structured_entry_matches_query,
    structured_inputs as _structured_inputs,
)


def build_xprompts_catalog(output_dir: Path | None = None) -> CatalogArtifact:
    """Gather every xprompt, compute stats, and render a PDF catalog."""
    _sync_catalog_source_dependencies()
    from ._catalog_render import build_xprompts_catalog as _build

    return _build(output_dir=output_dir)


def build_structured_xprompts_catalog(
    *,
    project: str | None = None,
    source: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    include_pdf: bool = False,
    limit: int | None = None,
) -> StructuredCatalogProjection:
    """Return a mobile-safe structured xprompt catalog projection."""
    _sync_catalog_source_dependencies()
    from ._catalog_structured import build_structured_xprompts_catalog as _build

    return _build(
        project=project,
        source=source,
        tag=tag,
        query=query,
        include_pdf=include_pdf,
        limit=limit,
    )


def _gather_entries() -> list[CatalogEntry]:
    _sync_catalog_source_dependencies()
    return _sources.gather_entries()


def _gather_structured_entries() -> list[StructuredCatalogSource]:
    _sync_catalog_source_dependencies()
    return _sources.gather_structured_entries()


def _classify(xp: XPrompt, project: str | None) -> CatalogEntry:
    _sync_catalog_source_dependencies()
    return _classify_impl(xp, project)


def _classify_xprompt_for_structured(
    xp: XPrompt, project: str | None
) -> StructuredCatalogSource:
    _sync_catalog_source_dependencies()
    return _classify_xprompt_for_structured_impl(xp, project)


def _classify_workflow(
    name: str, workflow: Workflow, project: str | None
) -> StructuredCatalogSource:
    _sync_catalog_source_dependencies()
    return _classify_workflow_impl(name, workflow, project)


def _entry_source_path(entry: CatalogEntry | StructuredCatalogSource) -> str | None:
    return _entry_source_path_impl(entry)


def _source_path_display(
    entry: CatalogEntry | StructuredCatalogSource,
) -> str | None:
    _sync_catalog_source_dependencies()
    return _sources.source_path_display(entry)


def _safe_path_display(path: Path) -> str | None:
    return _sources.safe_path_display(path)


def _safe_file_size(path: Path) -> int | None:
    return _sources.safe_file_size(path)


def _package_xprompt_dirs() -> list[Path]:
    _sync_catalog_source_dependencies()
    return _package_xprompt_dirs_impl()


def _sync_catalog_source_dependencies() -> None:
    """Keep legacy monkeypatch targets on this facade effective."""
    _sources.get_all_workflows = get_all_workflows
    _sources.get_all_xprompts = get_all_xprompts
    _sources.get_known_project_workspaces = get_known_project_workspaces
    _sources.get_sase_package_default_xprompts_dir = (
        get_sase_package_default_xprompts_dir
    )
    _sources.get_sase_package_xprompts_dir = get_sase_package_xprompts_dir
    _sources.load_project_local_xprompts = load_project_local_xprompts


__all__ = [
    "MAX_CONTENT_LINES",
    "MAX_MOBILE_CONTENT_PREVIEW_CHARS",
    "SOURCE_BUCKET_LABELS",
    "SOURCE_BUCKETS",
    "CatalogArtifact",
    "CatalogDocument",
    "CatalogEntry",
    "CatalogStats",
    "NoXpromptsFound",
    "PdfEngineUnavailable",
    "StructuredCatalogAttachment",
    "StructuredCatalogEntry",
    "StructuredCatalogInput",
    "StructuredCatalogProjection",
    "StructuredCatalogSkipped",
    "StructuredCatalogSource",
    "StructuredCatalogStats",
    "_CatalogDocument",
    "_CatalogEntry",
    "_StructuredCatalogSource",
    "_bar_width",
    "_build_document",
    "_classify",
    "_classify_workflow",
    "_classify_xprompt_for_structured",
    "_compute_stats",
    "_content_preview",
    "_default_display",
    "_display_label",
    "_entry_source_path",
    "_filter_structured_catalog_entries",
    "_format_inputs",
    "_gather_entries",
    "_gather_structured_entries",
    "_package_xprompt_dirs",
    "_render_html",
    "_render_pdf",
    "_safe_file_size",
    "_safe_path_display",
    "_source_path_display",
    "_structured_entry",
    "_structured_entry_matches_query",
    "_structured_inputs",
    "_tag_color_class",
    "_truncate_content",
    "build_structured_xprompts_catalog",
    "build_xprompts_catalog",
    "get_all_workflows",
    "get_all_xprompts",
    "get_known_project_workspaces",
    "get_sase_package_default_xprompts_dir",
    "get_sase_package_xprompts_dir",
    "load_project_local_xprompts",
    "shutil",
]
