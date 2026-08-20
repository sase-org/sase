"""Immutable models for the shared snippet catalog and mutation service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.snippet_catalog_facade import (
    ComposedSnippetCatalog,
    SnippetCall,
    SnippetDiagnostic as RustSnippetDiagnostic,
    SnippetSourceSpan,
    SnippetTriggerValidation,
)

SnippetSourceKind = Literal[
    "xprompt",
    "default",
    "plugin",
    "user",
    "overlay",
    "project",
    "configured",
    "pending",
]
SnippetMutationAction = Literal["created", "replaced", "shadowed", "deleted"]


@dataclass(frozen=True, slots=True)
class SnippetCatalogContext:
    """Resolved project identity for one catalog load."""

    key: str | None
    name: str | None
    aliases: tuple[str, ...]
    workspace_dir: Path | None


@dataclass(frozen=True, slots=True)
class SnippetSourceContribution:
    """One layer's authored definition of a trigger, including shadowed copies."""

    trigger: str
    template: str
    kind: SnippetSourceKind
    path: str | None
    display_path: str | None
    writable: bool
    xprompt_name: str | None = None
    description: str | None = None
    shadowed_by: str | None = None


@dataclass(frozen=True, slots=True)
class SnippetLayerDiagnostic:
    """Actionable diagnostic attached to one config or xprompt source."""

    message: str
    path: str | None = None
    layer: str | None = None
    trigger: str | None = None


@dataclass(frozen=True, slots=True)
class SnippetRelations:
    """Outbound/inbound indexes plus the scanned calls for one explicit trigger."""

    outbound: tuple[str, ...]
    inbound: tuple[str, ...]
    calls: tuple[SnippetCall, ...]


@dataclass(frozen=True, slots=True)
class SnippetEntry:
    """One effective explicit trigger in alphabetic catalog order."""

    trigger: str
    raw_template: str
    composed_template: str
    origin: SnippetSourceContribution
    aliases: tuple[str, ...]
    contributions: tuple[SnippetSourceContribution, ...]
    relations: SnippetRelations
    diagnostics: tuple[RustSnippetDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class SnippetCatalog:
    """Provenance-aware catalog of explicit snippets for one project context."""

    context: SnippetCatalogContext
    entries: tuple[SnippetEntry, ...]
    composed: ComposedSnippetCatalog
    layer_diagnostics: tuple[SnippetLayerDiagnostic, ...]
    explicit_templates: dict[str, str]
    effective_config_templates: dict[str, str]

    @property
    def composed_templates(self) -> dict[str, str]:
        return self.composed.templates

    @property
    def alias_provenance(self) -> dict[str, str]:
        return self.composed.alias_provenance

    def entry_for(self, trigger: str) -> SnippetEntry | None:
        for entry in self.entries:
            if entry.trigger == trigger:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class SnippetMutationOutcome:
    """Result of a planned or applied snippet add, update, or delete."""

    project_name: str
    trigger: str
    template: str
    action: SnippetMutationAction
    read_path: str
    write_path: str
    apply_target: str | None
    source_kind: str
    via_chezmoi: bool
    restore_command: str
    affected_backlinks: tuple[str, ...]
    revealed: SnippetEntry | None
    dry_run: bool
    content_digest: str
    created: bool


__all__ = [
    "SnippetCall",
    "SnippetCatalog",
    "SnippetCatalogContext",
    "SnippetEntry",
    "SnippetLayerDiagnostic",
    "SnippetMutationAction",
    "SnippetMutationOutcome",
    "SnippetRelations",
    "SnippetSourceContribution",
    "SnippetSourceKind",
    "SnippetSourceSpan",
    "SnippetTriggerValidation",
]
