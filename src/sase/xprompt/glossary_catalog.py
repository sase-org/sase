"""Project-aware glossary catalogs for editor integrations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.config._edit_yaml_io import make_yaml
from sase.content_layout import resolve_project_config_read_path
from sase.core.glossary_facade import (
    CompiledGlossaryCatalog,
    GlossaryCatalog,
    GlossaryDiagnostic,
    GlossaryEntry,
    GlossaryInputEntry,
    GlossarySource,
    build_glossary_catalog,
    compile_glossary_catalog,
    validate_glossary_entries,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name
from sase.glossary_config import GLOSSARY_CONFIG_KEY, resolve_glossary_config
from sase.xprompt._parsing_vcs_refs import resolve_known_project_ref

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
class EditorGlossaryProject:
    """The enabled project/workspace selected for glossary semantics."""

    key: str
    name: str
    aliases: tuple[str, ...]
    workspace_dir: Path

    def to_wire(self) -> dict[str, object]:
        return {
            "key": self.key,
            "name": self.name,
            "aliases": list(self.aliases),
            "workspace_dir": str(self.workspace_dir),
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
            else "no enabled project matched the active workspace"
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
    loaded, diagnostics = _load_round_trip_mapping(config_path)
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

    lines = _read_lines(config_path)
    entries, shape_errors = _glossary_entries(
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

    diagnostics = _validation_diagnostics(
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
    for record in _sort_records_for_catalog(records):
        project = _project_from_record(record)
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


def select_project(
    project_ref: str | None,
    records: Sequence[ProjectRecordWire],
    *,
    launch_workspace: str | Path | None,
) -> EditorGlossaryProject | None:
    if project_ref:
        record = _record_for_ref(project_ref, records)
        return None if record is None else _project_from_record(record)

    record = glossary_project_record_for_workspace(launch_workspace, records)
    return None if record is None else _project_from_record(record)


def _record_for_ref(
    project_ref: str,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    folded = project_ref.casefold()
    for record in records:
        refs = (record.project_name, effective_project_name(record), *record.aliases)
        if any(ref.casefold() == folded for ref in refs if ref):
            return record

    known_projects = {
        record.project_name: Path(str(record.workspace_dir))
        for record in records
        if record.workspace_dir
    }
    resolved = resolve_known_project_ref(project_ref, known_projects)
    if resolved is None:
        return None
    return next(
        (record for record in records if record.project_name == resolved),
        None,
    )


def glossary_project_record_for_workspace(
    launch_workspace: str | Path | None,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    """Return the enabled record containing *launch_workspace*, or CWD's.

    Shared by :func:`editor_glossary_catalog_for_project`'s CWD-fallback
    resolution and the ACE glossary panel's project-ring builder, which
    needs the launch project even when it declares no glossary.
    """
    workspace = (
        Path(launch_workspace).expanduser()
        if launch_workspace is not None
        else _safe_cwd()
    )
    if workspace is None:
        return None
    return _record_for_workspace(workspace, records)


def _record_for_workspace(
    workspace: Path,
    records: Sequence[ProjectRecordWire],
) -> ProjectRecordWire | None:
    try:
        resolved_workspace = workspace.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None
    for record in records:
        if not record.workspace_dir:
            continue
        try:
            candidate = Path(record.workspace_dir).expanduser().resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        if _is_relative_to(resolved_workspace, candidate):
            return record
    return None


def _project_from_record(record: ProjectRecordWire) -> EditorGlossaryProject | None:
    if not record.workspace_dir:
        return None
    return EditorGlossaryProject(
        key=record.project_name,
        name=effective_project_name(record),
        aliases=tuple(dict.fromkeys(record.aliases)),
        workspace_dir=Path(record.workspace_dir).expanduser().resolve(strict=False),
    )


def _sort_records_for_catalog(
    records: Iterable[ProjectRecordWire],
) -> list[ProjectRecordWire]:
    return sorted(
        records,
        key=lambda record: (
            effective_project_name(record).casefold(),
            record.project_name.casefold(),
        ),
    )


def _load_round_trip_mapping(
    config_path: Path,
) -> tuple[Mapping[Any, Any] | None, tuple[str, ...]]:
    if not config_path.exists():
        return None, ()
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, (f"{config_path}: failed to read file: {exc}",)
    try:
        data = make_yaml().load(text)
    except Exception as exc:
        return None, (f"{config_path}: failed to parse YAML: {exc}",)
    if data is None:
        return {}, ()
    if not isinstance(data, Mapping):
        return None, (f"{config_path}: expected a YAML mapping at the top level",)
    return data, ()


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _glossary_entries(
    config_path: Path,
    raw: Any,
    lines: Sequence[str],
    *,
    config_key_path: tuple[str, ...],
    display_path: str,
) -> tuple[tuple[GlossaryInputEntry, ...], tuple[str, ...]]:
    prefix = f"{config_path}: {display_path}"
    if not isinstance(raw, Mapping):
        return (), (f"{prefix} must be a mapping",)

    errors: list[str] = []
    entries: list[GlossaryInputEntry] = []
    for term, value in raw.items():
        term_path = _path_component(term)
        path = f"{display_path}.{term_path}"
        if not isinstance(term, str) or not term.strip() or _has_newline(term):
            errors.append(f"{config_path}: {path}: term must be a nonblank string")
            continue
        if not isinstance(value, Mapping):
            errors.append(f"{config_path}: {path} must be a mapping")
            continue

        unexpected = sorted(
            str(key) for key in value if key not in {"definition", "aliases"}
        )
        for key in unexpected:
            errors.append(f"{config_path}: {path}.{key}: unknown glossary field")

        definition = value.get("definition")
        if not isinstance(definition, str) or not definition.strip():
            errors.append(f"{config_path}: {path}.definition must be a nonblank string")
            continue

        raw_aliases = value.get("aliases", [])
        aliases: list[str] = []
        if not isinstance(raw_aliases, list):
            errors.append(f"{config_path}: {path}.aliases must be a list")
            continue
        for index, alias in enumerate(raw_aliases):
            alias_path = f"{path}.aliases[{index}]"
            if not isinstance(alias, str) or not alias.strip():
                errors.append(f"{config_path}: {alias_path} must be a nonblank string")
                continue
            if _has_newline(alias):
                errors.append(
                    f"{config_path}: {alias_path} must be a single-line string"
                )
                continue
            aliases.append(alias)

        entries.append(
            GlossaryInputEntry(
                term=term,
                definition=definition,
                aliases=tuple(aliases),
                source=_glossary_source(
                    config_path,
                    raw,
                    term,
                    value,
                    lines,
                    config_key_path=config_key_path,
                ),
            )
        )
    return tuple(entries), tuple(errors)


def _glossary_source(
    config_path: Path,
    glossary_node: Mapping[Any, Any],
    term: str,
    entry_node: Mapping[Any, Any],
    lines: Sequence[str],
    *,
    config_key_path: tuple[str, ...],
) -> GlossarySource:
    term_range = _key_range(glossary_node, term)
    definition_range = _value_range(entry_node, "definition", lines)
    aliases_range = _value_range(entry_node, "aliases", lines)
    return GlossarySource(
        config_path=str(config_path),
        config_key_path=(*config_key_path, term),
        term_range=term_range,
        definition_range=definition_range,
        aliases_range=aliases_range,
    )


def _validation_diagnostics(
    config_path: Path,
    entries: Sequence[GlossaryInputEntry],
    *,
    display_path: str,
) -> tuple[str, ...]:
    try:
        diagnostics = validate_glossary_entries(entries)
    except (AttributeError, ImportError, ValueError, RuntimeError) as exc:
        return (f"{config_path}: failed to validate glossary: {exc}",)

    errors = tuple(
        _format_diagnostic(config_path, diagnostic, display_path=display_path)
        for diagnostic in diagnostics
        if diagnostic.severity == "error"
    )
    return errors


def _format_diagnostic(
    config_path: Path,
    diagnostic: GlossaryDiagnostic,
    *,
    display_path: str,
) -> str:
    path = _diagnostic_path(diagnostic.path, display_path)
    return f"{config_path}: {path}: {diagnostic.message}"


def _diagnostic_path(path: str | None, display_path: str) -> str:
    if not path:
        return display_path
    if path == GLOSSARY_CONFIG_KEY:
        return display_path
    if path.startswith(f"{GLOSSARY_CONFIG_KEY}."):
        return f"{display_path}{path.removeprefix(GLOSSARY_CONFIG_KEY)}"
    return path


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


def _key_range(node: Mapping[Any, Any], key: str) -> dict[str, object] | None:
    location = _node_key_location(node, key)
    if location is None:
        return None
    line, column, _, _ = location
    return {
        "start": {"line": line, "character": column},
        "end": {"line": line, "character": column + len(key)},
    }


def _value_range(
    node: Mapping[Any, Any],
    key: str,
    lines: Sequence[str],
) -> dict[str, object] | None:
    location = _node_key_location(node, key)
    if location is None:
        return None
    key_line, key_col, value_line, value_col = location
    end_line = _block_end(lines, key_line, key_col) - 1
    end_line = max(value_line, min(end_line, len(lines) - 1)) if lines else value_line
    end_char = len(lines[end_line]) if 0 <= end_line < len(lines) else value_col
    return {
        "start": {"line": value_line, "character": value_col},
        "end": {"line": end_line, "character": end_char},
    }


def _node_key_location(
    node: Mapping[Any, Any],
    key: str,
) -> tuple[int, int, int, int] | None:
    data = getattr(getattr(node, "lc", None), "data", None)
    if not isinstance(data, dict):
        return None
    location = data.get(key)
    if not isinstance(location, list | tuple) or len(location) < 4:
        return None
    try:
        return (
            int(location[0]),
            int(location[1]),
            int(location[2]),
            int(location[3]),
        )
    except (TypeError, ValueError):
        return None


def _block_end(lines: Sequence[str], start_line: int, indent: int) -> int:
    if not lines or start_line < 0 or start_line >= len(lines):
        return start_line + 1
    last_content_end = start_line + 1
    for index in range(start_line + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped and _line_indent(line) <= indent:
            break
        if stripped:
            last_content_end = index + 1
    return last_content_end


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


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


def _safe_cwd() -> Path | None:
    try:
        return Path.cwd()
    except OSError:
        return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _path_component(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    return repr(value)


def _has_newline(value: str) -> bool:
    return "\n" in value or "\r" in value


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
