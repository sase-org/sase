"""Project-aware glossary catalogs for editor integrations.

Public surface:
- :func:`editor_glossary_catalog_for_project`
- :func:`editor_glossary_lsp_catalog_payload`

Project resolution lives in :mod:`sase.xprompt._glossary_catalog_projects`, and
config reading/shaping in :mod:`sase.xprompt._glossary_catalog_config`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.content_layout import resolve_project_config_read_path
from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    GlossaryEntry,
    build_glossary_catalog,
    compile_glossary_catalog,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.glossary_config import GLOSSARY_CONFIG_KEY, resolve_glossary_config
from sase.xprompt._glossary_catalog_config import (
    load_round_trip_mapping,
    parse_glossary_entries,
    read_config_lines,
    validation_diagnostics,
)
from sase.xprompt._glossary_catalog_projects import (
    EditorGlossaryProject,
    glossary_project_record_for_workspace,
    project_from_record,
    select_project,
    sort_records_for_catalog,
)

EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class _GlossaryConfigSignature:
    """Filesystem signature used by editor caches to detect config changes."""

    path: str
    mtime_ns: int
    size: int

    def to_wire(self) -> dict[str, object]:
        return {
            "path": self.path,
            "mtime_ns": self.mtime_ns,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class EditorGlossaryCatalog:
    """A normalized glossary catalog plus the compiled native matcher handle."""

    schema_version: int
    project: EditorGlossaryProject
    config_path: Path
    config_signature: _GlossaryConfigSignature
    catalog: GlossaryCatalog
    compiled: CompiledGlossaryCatalog

    @property
    def entries(self) -> tuple[GlossaryEntry, ...]:
        return self.catalog.entries

    def to_wire(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project": self.project.to_wire(),
            "config_path": str(self.config_path),
            "config_signature": self.config_signature.to_wire(),
            "entries": [_entry_to_wire(entry) for entry in self.catalog.entries],
        }


@dataclass(frozen=True, slots=True)
class EditorGlossaryCatalogResult:
    """Best-effort glossary load result for editor warmers."""

    project: EditorGlossaryProject | None
    catalog: EditorGlossaryCatalog | None
    diagnostics: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.catalog is not None and not self.diagnostics


def editor_glossary_catalog_for_project(
    project_ref: str | None = None,
    *,
    launch_workspace: str | Path | None = None,
    projects_root: str | Path | None = None,
) -> EditorGlossaryCatalogResult:
    """Load one enabled project's glossary catalog by key, name, alias, or CWD."""

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
            else "no enabled project matched the active workspace; pass -p/--project"
        )
        return EditorGlossaryCatalogResult(None, None, (detail,))
    return _load_editor_glossary_catalog(project)


def _load_editor_glossary_catalog(
    project: EditorGlossaryProject,
) -> EditorGlossaryCatalogResult:
    """Load and compile the project-local glossary for an exact project."""

    try:
        config_path = resolve_project_config_read_path(
            project.workspace_dir,
            label=f"project config for {project.key}",
        )
    except Exception as exc:
        return EditorGlossaryCatalogResult(
            project,
            None,
            (f"{project.key}: failed to resolve project config: {exc}",),
        )
    if config_path is None:
        return EditorGlossaryCatalogResult(project, None, ())

    config_path = config_path.expanduser().resolve(strict=False)
    loaded, diagnostics = load_round_trip_mapping(config_path)
    if diagnostics:
        return EditorGlossaryCatalogResult(project, None, diagnostics)
    if loaded is None:
        return EditorGlossaryCatalogResult(project, None, ())

    resolution = resolve_glossary_config(loaded)
    if resolution.error is not None:
        return EditorGlossaryCatalogResult(
            project,
            None,
            (f"{config_path}: {resolution.error}",),
        )
    if not resolution.declared or resolution.node is None:
        return EditorGlossaryCatalogResult(project, None, ())

    lines = read_config_lines(config_path)
    entries, shape_errors = parse_glossary_entries(
        config_path,
        resolution.node,
        lines,
        config_key_path=resolution.key_path,
        display_path=resolution.display_path,
    )
    if shape_errors:
        return EditorGlossaryCatalogResult(project, None, shape_errors)
    if not entries:
        return EditorGlossaryCatalogResult(project, None, ())

    diagnostics = validation_diagnostics(
        config_path,
        entries,
        display_path=resolution.display_path,
    )
    if diagnostics:
        return EditorGlossaryCatalogResult(project, None, diagnostics)

    try:
        catalog = build_glossary_catalog(entries)
        compiled = compile_glossary_catalog(entries)
    except (AttributeError, ImportError, ValueError, RuntimeError) as exc:
        return EditorGlossaryCatalogResult(
            project,
            None,
            (f"{config_path}: failed to build glossary catalog: {exc}",),
        )

    signature = _config_signature(config_path)
    if signature is None:
        return EditorGlossaryCatalogResult(
            project,
            None,
            (f"{config_path}: failed to stat glossary config",),
        )

    return EditorGlossaryCatalogResult(
        project,
        EditorGlossaryCatalog(
            schema_version=EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
            project=project,
            config_path=config_path,
            config_signature=signature,
            catalog=catalog,
            compiled=compiled,
        ),
    )


def editor_glossary_lsp_catalog_payload(
    launch_workspace: str | Path | None = None,
    *,
    projects_root: str | Path | None = None,
) -> dict[str, object]:
    """Return the JSON-serializable glossary catalog consumed by the LSP."""

    records = enabled_project_records(projects_root)
    default_project = select_project(
        None,
        records,
        launch_workspace=launch_workspace,
    )
    projects: list[dict[str, object]] = []
    for record in sort_records_for_catalog(records):
        project = project_from_record(record)
        if project is None:
            continue
        result = _load_editor_glossary_catalog(project)
        if result.catalog is None:
            continue
        projects.append(result.catalog.to_wire())

    return {
        "schema_version": EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
        "default_project": None if default_project is None else default_project.key,
        "projects": projects,
    }


def enabled_project_records(
    projects_root: str | Path | None,
) -> tuple[ProjectRecordWire, ...]:
    """Return enabled, non-system, on-disk project records for glossary use.

    Shared by :func:`editor_glossary_catalog_for_project` and the ACE
    glossary panel's project ring builder so both apply the same filtering.
    """
    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    try:
        records = list_project_records(
            root,
            ("enabled",),
            include_home=False,
            projects_only=True,
        )
    except Exception:
        return ()
    return tuple(
        record
        for record in records
        if record.is_project
        and not record.system_managed
        and record.workspace_dir
        and Path(record.workspace_dir).expanduser().is_dir()
    )


def _config_signature(path: Path) -> _GlossaryConfigSignature | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return _GlossaryConfigSignature(
        path=str(path),
        mtime_ns=stat.st_mtime_ns,
        size=stat.st_size,
    )


def _entry_to_wire(entry: GlossaryEntry) -> dict[str, object]:
    return {
        "index": entry.index,
        "term": entry.term,
        "normalized_term": entry.normalized_term,
        "definition": entry.definition,
        "configured_aliases": list(entry.configured_aliases),
        "display_aliases": list(entry.display_aliases),
        "effective_aliases": list(entry.effective_aliases),
        "source": entry.source,
    }


__all__ = [
    "EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION",
    "GLOSSARY_CONFIG_KEY",
    "EditorGlossaryCatalog",
    "EditorGlossaryCatalogResult",
    "EditorGlossaryProject",
    "editor_glossary_catalog_for_project",
    "editor_glossary_lsp_catalog_payload",
    "enabled_project_records",
    "glossary_project_record_for_workspace",
    "select_project",
]
