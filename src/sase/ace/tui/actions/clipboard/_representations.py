"""Pure records and formatters for artifact copy representations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal

from ...widgets.artifacts.entry_navigation import ArtifactEntryTarget
from ._helpers import format_markdown_link


ArtifactRepresentation = Literal["reference", "link", "json"]


@dataclass(frozen=True, slots=True)
class ArtifactReferenceItem:
    """One captured Artifacts row and its representation labels."""

    label: str
    target: ArtifactEntryTarget
    row: object | None
    project: str | None
    workspace_dir: str
    markdown_label: str = ""
    kind_label: str = "artifact"


@dataclass(frozen=True, slots=True)
class ArtifactReferenceSelection:
    """Stable Artifacts selection captured before off-pump resolution."""

    subtab: str
    items: tuple[ArtifactReferenceItem, ...]
    marked: bool
    prompt_project: str | None
    prompt_display_name: str | None
    prompt_project_file: str | None


@dataclass(frozen=True, slots=True)
class ResolvedArtifactItem:
    """One representable item with optional CLI metadata JSON."""

    item: ArtifactReferenceItem
    reference: str
    metadata: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ResolvedArtifactSelection:
    """Representable items plus per-entry failures from a marked set."""

    items: tuple[ResolvedArtifactItem, ...]
    failures: tuple[str, ...]


def format_artifact_representation(
    representation: ArtifactRepresentation,
    items: tuple[ResolvedArtifactItem, ...],
    *,
    marked: bool,
) -> str:
    """Build a paste-ready single or marked-set representation."""

    if representation == "reference":
        values = [f"@{item.reference}" for item in items]
        return "\n".join(values) if marked else values[0]
    if representation == "link":
        values = [
            format_markdown_link(
                item.item.markdown_label or item.item.label,
                item.reference,
            )
            for item in items
        ]
        return "\n".join(f"- {value}" for value in values) if marked else values[0]
    payloads = [item.metadata for item in items]
    payload: object = payloads if marked else payloads[0]
    return json.dumps(payload, indent=2)


def artifact_representation_label(
    representation: ArtifactRepresentation,
    items: tuple[ResolvedArtifactItem, ...],
    *,
    marked: bool,
    failure_count: int,
) -> str:
    """Name exactly what a representation copy delivered."""

    if representation == "reference":
        label = "artifact reference" if not marked else f"{len(items)} references"
    elif representation == "link":
        label = (
            f"{items[0].item.kind_label} Markdown link"
            if not marked
            else f"{len(items)} Markdown links"
        )
    else:
        label = (
            f"{items[0].item.kind_label} metadata JSON"
            if not marked
            else f"{len(items)} metadata JSON records"
        )
    if failure_count:
        noun = "entry" if failure_count == 1 else "entries"
        label += f" — {failure_count} {noun} have no reference"
    return label


__all__ = [
    "ArtifactReferenceItem",
    "ArtifactReferenceSelection",
    "ArtifactRepresentation",
    "ResolvedArtifactItem",
    "ResolvedArtifactSelection",
    "artifact_representation_label",
    "format_artifact_representation",
]
