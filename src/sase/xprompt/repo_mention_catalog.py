"""Project-scoped repo-mention catalogs for editor integrations.

Repo identifiers are fed into the same Rust glossary matcher the project
glossary uses (``compile_glossary_catalog`` / ``scan_glossary_spans`` /
``lookup_glossary_span``), so matching semantics stay identical between the
two overlays by construction. This module owns everything the matcher does
not: which repo records are admitted as identifiers, dropping the matcher's
derived plurals, and rejecting path-adjacent matches (``../sase-core``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config._edit_yaml_io import make_yaml
from sase.content_layout import resolve_project_config_read_path
from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryInputEntry,
    GlossarySpan,
    compile_glossary_catalog,
    lookup_glossary_span,
    scan_glossary_spans,
)
from sase.repo_inventory import RepoKind, RepoRecord, collect_repo_inventory
from sase.xprompt.glossary_catalog import (
    EditorGlossaryProject,
    enabled_project_records,
    select_project,
    editor_glossary_catalog_for_project,
)

EDITOR_REPO_MENTION_CATALOG_SCHEMA_VERSION = 1

_PATH_ADJACENT_BEFORE = frozenset({b"/", b"\\", b"."})
_PATH_ADJACENT_AFTER = frozenset({b"/", b"\\"})


@dataclass(frozen=True, slots=True)
class RepoMention:
    """One admitted repo identifier resolved against its inventory record."""

    identifier: str
    kind: RepoKind
    record: RepoRecord
    index: int
    config_path: str | None
    config_line: int | None
    config_col: int | None


@dataclass(frozen=True, slots=True)
class EditorRepoMentionCatalog:
    """A compiled repo-mention catalog for one project."""

    schema_version: int
    project: EditorGlossaryProject
    mentions: tuple[RepoMention, ...]
    compiled: CompiledGlossaryCatalog

    def mention_for_index(self, index: int) -> RepoMention | None:
        if 0 <= index < len(self.mentions):
            return self.mentions[index]
        return None


@dataclass(frozen=True, slots=True)
class EditorRepoMentionCatalogResult:
    """Best-effort repo-mention catalog load result for editor warmers."""

    project: EditorGlossaryProject | None
    catalog: EditorRepoMentionCatalog | None
    diagnostics: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.catalog is not None and not self.diagnostics


@dataclass(frozen=True, slots=True)
class RepoMentionSpan:
    """A repo-mention match: the resolved mention plus its underlying span."""

    mention: RepoMention
    glossary_span: GlossarySpan

    @property
    def matched_text(self) -> str:
        return self.glossary_span.matched_text

    @property
    def byte_start(self) -> int:
        return self.glossary_span.byte_start

    @property
    def byte_end(self) -> int:
        return self.glossary_span.byte_end

    @property
    def range(self) -> Mapping[str, Any]:
        return self.glossary_span.range

    @property
    def segments(self) -> tuple[Mapping[str, Any], ...]:
        return self.glossary_span.segments


def editor_repo_mention_catalog_for_project(
    project_ref: str | None = None,
    *,
    launch_workspace: str | Path | None = None,
    projects_root: str | Path | None = None,
) -> EditorRepoMentionCatalogResult:
    """Load one enabled project's repo-mention catalog by key, name, alias, or CWD."""

    records = enabled_project_records(projects_root)
    project = select_project(
        project_ref,
        records,
        launch_workspace=launch_workspace,
    )
    if project is None:
        detail = (
            f"project ref {project_ref!r} did not resolve to an enabled workspace"
            if project_ref
            else "no enabled project matched the active workspace"
        )
        return EditorRepoMentionCatalogResult(None, None, (detail,))
    return _load_editor_repo_mention_catalog(project, projects_root=projects_root)


def _load_editor_repo_mention_catalog(
    project: EditorGlossaryProject,
    *,
    projects_root: str | Path | None,
) -> EditorRepoMentionCatalogResult:
    try:
        inventory = collect_repo_inventory(projects_root, project=project.key)
    except Exception as exc:
        return EditorRepoMentionCatalogResult(
            project,
            None,
            (f"{project.key}: failed to collect repo inventory: {exc}",),
        )

    candidates = _admitted_candidates(inventory.records)
    if not candidates:
        return EditorRepoMentionCatalogResult(project, None, ())

    diagnostics: list[str] = []
    excluded = _glossary_excluded_identifiers(project, projects_root, diagnostics)
    admitted = [
        (identifier, record)
        for identifier, record in candidates
        if identifier.casefold() not in excluded
    ]
    if not admitted:
        return EditorRepoMentionCatalogResult(project, None, tuple(diagnostics))

    entries = tuple(
        GlossaryInputEntry(term=identifier, definition=_synthesized_definition(record))
        for identifier, record in admitted
    )
    try:
        compiled = compile_glossary_catalog(entries)
    except (AttributeError, ImportError, ValueError, RuntimeError) as exc:
        return EditorRepoMentionCatalogResult(
            project,
            None,
            (*diagnostics, f"{project.key}: failed to compile repo catalog: {exc}"),
        )

    config_path, document = _repo_config_document(project)
    mentions = tuple(
        _build_repo_mention(identifier, record, index, config_path, document)
        for index, (identifier, record) in enumerate(admitted)
    )

    return EditorRepoMentionCatalogResult(
        project,
        EditorRepoMentionCatalog(
            schema_version=EDITOR_REPO_MENTION_CATALOG_SCHEMA_VERSION,
            project=project,
            mentions=mentions,
            compiled=compiled,
        ),
        tuple(diagnostics),
    )


def _build_repo_mention(
    identifier: str,
    record: RepoRecord,
    index: int,
    config_path: Path | None,
    document: Mapping[Any, Any] | None,
) -> RepoMention:
    location = _declaration_location(record, document)
    line, col = (
        (location[0] + 1, location[1] + 1) if location is not None else (None, None)
    )
    return RepoMention(
        identifier=identifier,
        kind=record.kind,
        record=record,
        index=index,
        config_path=(
            str(config_path)
            if config_path is not None and record.kind != "external"
            else None
        ),
        config_line=line,
        config_col=col,
    )


def _admitted_candidates(
    records: Sequence[RepoRecord],
) -> list[tuple[str, RepoRecord]]:
    seen: set[str] = set()
    candidates: list[tuple[str, RepoRecord]] = []
    for record in records:
        identifier = _admitted_identifier(record)
        if not identifier or any(char.isspace() for char in identifier):
            continue
        folded = identifier.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        candidates.append((identifier, record))
    return candidates


def _admitted_identifier(record: RepoRecord) -> str | None:
    if record.kind == "linked":
        return record.name
    if record.kind == "sidecar":
        return record.slug
    if record.kind == "external":
        return record.name
    return None


def _glossary_excluded_identifiers(
    project: EditorGlossaryProject,
    projects_root: str | Path | None,
    diagnostics: list[str],
) -> set[str]:
    result = editor_glossary_catalog_for_project(
        project.key, projects_root=projects_root
    )
    if result.diagnostics:
        diagnostics.append(
            f"{project.key}: glossary catalog unavailable for repo-name "
            f"exclusions: {'; '.join(result.diagnostics)}"
        )
        return set()
    if result.catalog is None:
        return set()
    excluded: set[str] = set()
    for entry in result.catalog.entries:
        excluded.add(entry.term.casefold())
        excluded.update(alias.casefold() for alias in entry.effective_aliases)
    return excluded


def _synthesized_definition(record: RepoRecord) -> str:
    description = (record.description or "").strip()
    if description:
        return description
    return f"{record.kind.capitalize()} repository at {record.path}."


def _repo_config_document(
    project: EditorGlossaryProject,
) -> tuple[Path | None, Mapping[Any, Any] | None]:
    try:
        config_path = resolve_project_config_read_path(
            project.workspace_dir,
            label=f"project config for {project.key}",
        )
    except Exception:
        return None, None
    if config_path is None:
        return None, None
    config_path = config_path.expanduser().resolve(strict=False)
    if not config_path.exists():
        return config_path, None
    try:
        text = config_path.read_text(encoding="utf-8")
        data = make_yaml().load(text)
    except Exception:
        return config_path, None
    if not isinstance(data, Mapping):
        return config_path, None
    return config_path, data


def _declaration_location(
    record: RepoRecord,
    document: Mapping[Any, Any] | None,
) -> tuple[int, int] | None:
    if document is None:
        return None
    if record.kind == "linked":
        return _linked_item_location(document, record.name)
    if record.kind == "sidecar":
        return _sidecar_role_location(document, record.name)
    return None


def _linked_item_location(
    document: Mapping[Any, Any],
    name: str,
) -> tuple[int, int] | None:
    repos = document.get("repos")
    if not isinstance(repos, Mapping):
        return None
    linked = repos.get("linked")
    if not isinstance(linked, Sequence) or isinstance(linked, str | bytes):
        return None
    for index, item in enumerate(linked):
        if isinstance(item, Mapping) and item.get("name") == name:
            return _lc_location(linked, index)
    return None


def _sidecar_role_location(
    document: Mapping[Any, Any],
    role: str,
) -> tuple[int, int] | None:
    repos = document.get("repos")
    if not isinstance(repos, Mapping):
        return None
    sidecar = repos.get("sidecar")
    if not isinstance(sidecar, Mapping):
        return None
    for bucket_key in ("builtin", "custom"):
        bucket = sidecar.get(bucket_key)
        if isinstance(bucket, Mapping) and role in bucket:
            return _lc_location(bucket, role)
    return None


def _lc_location(node: Any, key: Any) -> tuple[int, int] | None:
    data = getattr(getattr(node, "lc", None), "data", None)
    if not isinstance(data, dict):
        return None
    location = data.get(key)
    if not isinstance(location, list | tuple) or len(location) < 2:
        return None
    try:
        return int(location[0]), int(location[1])
    except (TypeError, ValueError):
        return None


def scan_repo_mentions(
    catalog: EditorRepoMentionCatalog,
    text: str,
) -> tuple[RepoMentionSpan, ...]:
    """Scan *text* with a compiled repo-mention catalog.

    Applies the exact-identifier filter (rejecting the Rust matcher's derived
    plurals) and the path-adjacency filter (rejecting spans immediately
    preceded by ``/``, ``\\``, or ``.``, or immediately followed by ``/`` or
    ``\\``) on top of the raw Rust scan.
    """
    encoded = text.encode("utf-8")
    spans = tuple(
        resolved
        for span in scan_glossary_spans(catalog.compiled, text)
        if (resolved := _resolve_repo_mention_span(catalog, span, encoded)) is not None
    )
    return spans


def lookup_repo_mention(
    catalog: EditorRepoMentionCatalog,
    text: str,
    *,
    line: int,
    character: int,
) -> RepoMentionSpan | None:
    """Return the repo mention under a UTF-16 editor position, if any."""
    span = lookup_glossary_span(catalog.compiled, text, line=line, character=character)
    if span is None:
        return None
    return _resolve_repo_mention_span(catalog, span, text.encode("utf-8"))


def _resolve_repo_mention_span(
    catalog: EditorRepoMentionCatalog,
    span: GlossarySpan,
    encoded: bytes,
) -> RepoMentionSpan | None:
    mention = catalog.mention_for_index(span.entry_index)
    if mention is None:
        return None
    if span.matched_text.casefold() != mention.identifier.casefold():
        return None
    if not _passes_path_adjacency(encoded, span.byte_start, span.byte_end):
        return None
    return RepoMentionSpan(mention=mention, glossary_span=span)


def _passes_path_adjacency(encoded: bytes, byte_start: int, byte_end: int) -> bool:
    if byte_start > 0 and encoded[byte_start - 1 : byte_start] in _PATH_ADJACENT_BEFORE:
        return False
    if (
        byte_end < len(encoded)
        and encoded[byte_end : byte_end + 1] in _PATH_ADJACENT_AFTER
    ):
        return False
    return True


__all__ = [
    "EDITOR_REPO_MENTION_CATALOG_SCHEMA_VERSION",
    "EditorRepoMentionCatalog",
    "EditorRepoMentionCatalogResult",
    "RepoMention",
    "RepoMentionSpan",
    "editor_repo_mention_catalog_for_project",
    "lookup_repo_mention",
    "scan_repo_mentions",
]
