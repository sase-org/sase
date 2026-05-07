"""Shared models for the xprompt catalog builders."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sase.xprompt.models import XPrompt
from sase.xprompt.workflow_models import Workflow


class PdfEngineUnavailable(RuntimeError):
    """Raised when no HTML-capable PDF engine is available on PATH."""


class NoXpromptsFound(RuntimeError):
    """Raised when there are no xprompts to include in the catalog."""


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


@dataclass(frozen=True)
class CatalogArtifact:
    """Result of building the xprompt catalog."""

    pdf_path: Path
    stats: CatalogStats


@dataclass(frozen=True)
class StructuredCatalogInput:
    """Mobile-safe structured xprompt input metadata."""

    name: str
    type: str
    required: bool
    default_display: str | None
    position: int


@dataclass(frozen=True)
class StructuredCatalogEntry:
    """Mobile-safe structured xprompt catalog entry."""

    name: str
    display_label: str
    insertion: str
    reference_prefix: str
    kind: str
    description: str | None
    source_bucket: str
    project: str | None
    tags: list[str]
    input_signature: str | None
    inputs: list[StructuredCatalogInput]
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
class CatalogEntry:
    """Internal representation of an xprompt for rendering."""

    xprompt: XPrompt
    bucket: str
    project: str | None


@dataclass
class StructuredCatalogSource:
    """Internal workflow-like entry consumed by the mobile catalog projection."""

    name: str
    workflow: Workflow
    bucket: str
    project: str | None
    description: str | None = None
    is_skill: bool = False
    content: str = ""


@dataclass
class CatalogDocument:
    """In-memory model consumed by the HTML renderer."""

    entries_by_bucket: dict[str, list[CatalogEntry]]
    stats: CatalogStats
    sections: list[tuple[str, list[tuple[str | None, list[CatalogEntry]]]]] = field(
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

# Backwards-compatible private names exported by sase.xprompt.catalog.
_CatalogEntry = CatalogEntry
_StructuredCatalogSource = StructuredCatalogSource
_CatalogDocument = CatalogDocument
