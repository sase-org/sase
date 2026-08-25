"""Project-scoped glossary add/delete engine.

Python owns file discovery, source-preserving YAML edits, and the stale-write
guard. Rust still decides whether a candidate entry set is valid.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import stat
import tempfile
from typing import Any

from sase.config._edit_yaml import set_key, unset_key
from sase.config._edit_yaml_io import dump_yaml, make_yaml
from sase.config.core import clear_config_cache
from sase.content_layout import resolve_project_config_write_path
from sase.core.glossary_facade import (
    GlossaryDiagnostic,
    GlossaryInputEntry,
    validate_glossary_entries,
)
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.relations import glossary_reverse_references
from sase.glossary.resolution import (
    GlossaryLookupError,
    normalize_glossary_reference,
    resolve_glossary_closure,
)
from sase.glossary_config import resolve_glossary_config
from sase.xprompt.glossary_catalog import editor_glossary_catalog_for_project

_MEMORY_KEY = "memory"
_GLOSSARY_KEY = "glossary"


@dataclass(frozen=True, slots=True)
class GlossaryMutationOutcome:
    """Result of a successful glossary add or delete."""

    project_name: str
    config_path: str
    workspace_dir: str
    term: str
    aliases: tuple[str, ...]
    definition: str
    created_section: bool
    restore_command: str
    referenced_by: tuple[str, ...]


class GlossaryMutationError(RuntimeError):
    """Raised when a glossary add or delete cannot be applied."""


class GlossaryValidationError(GlossaryMutationError):
    """Raised when the candidate glossary set fails Rust validation."""

    def __init__(self, diagnostics: tuple[GlossaryDiagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        if diagnostics:
            message = "; ".join(f"{item.code}: {item.message}" for item in diagnostics)
        else:
            message = "glossary validation failed"
        super().__init__(message)


class GlossaryConflictError(GlossaryMutationError):
    """Raised when the config file changed between read and write."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"glossary config changed after preview: {path}; reload and retry the edit"
        )


def add_glossary_term(
    project_ref: str | None,
    term: str,
    definition: str,
    aliases: Sequence[str] = (),
) -> GlossaryMutationOutcome:
    """Insert *term* into the target project's glossary after Rust validation."""
    cleaned_term = require_glossary_term_text(term)
    cleaned_definition = require_glossary_definition_text(definition)
    cleaned_aliases = normalize_glossary_aliases(aliases)
    project = _resolve_project(project_ref, require_catalog=False)
    config_path = resolve_project_config_write_path(project.workspace_dir)
    original_bytes, text = _read_config_text(config_path)
    current_entries, created_section = _load_current_entries(text)
    candidate = (
        *current_entries,
        GlossaryInputEntry(
            term=cleaned_term,
            definition=cleaned_definition,
            aliases=cleaned_aliases,
        ),
    )
    validate_glossary_candidate(candidate)
    new_text = _apply_add_to_text(
        text, cleaned_term, cleaned_definition, cleaned_aliases
    )
    _write_config_atomically(config_path, new_text, original_bytes)
    return GlossaryMutationOutcome(
        project_name=project.name,
        config_path=str(config_path),
        workspace_dir=str(project.workspace_dir),
        term=cleaned_term,
        aliases=cleaned_aliases,
        definition=cleaned_definition,
        created_section=created_section,
        restore_command=glossary_restore_command(
            cleaned_term,
            cleaned_definition,
            cleaned_aliases,
            project.name,
        ),
        referenced_by=(),
    )


def delete_glossary_term(
    project_ref: str | None,
    reference: str,
    *,
    dry_run: bool = False,
) -> GlossaryMutationOutcome:
    """Remove the glossary entry resolved from *reference* after validation.

    When *dry_run* is true, resolve, validate, and return the outcome without
    writing the config file.
    """
    project = _resolve_project(project_ref, require_catalog=True)
    catalog = project.catalog
    compiled = project.compiled
    if catalog is None or compiled is None:
        raise GlossaryCliError(f"{project.name} has no glossary configured")
    entry = resolve_glossary_closure(catalog, compiled, (reference,), depth=0).roots[0]
    referenced_by = tuple(
        glossary_reverse_references(catalog, compiled).get(entry.index, ())
    )
    config_path = resolve_project_config_write_path(project.workspace_dir)
    original_bytes, text = _read_config_text(config_path)
    current_entries, _created_section = _load_current_entries(text)
    remaining = tuple(
        item
        for item in current_entries
        if normalize_glossary_reference(item.term)
        != normalize_glossary_reference(entry.term)
    )
    if len(remaining) == len(current_entries):
        raise GlossaryLookupError(reference)
    validate_glossary_candidate(remaining)
    new_text = unset_key(text, (_MEMORY_KEY, _GLOSSARY_KEY, entry.term))
    if not dry_run:
        _write_config_atomically(config_path, new_text, original_bytes)
    aliases = entry.configured_aliases
    return GlossaryMutationOutcome(
        project_name=project.name,
        config_path=str(config_path),
        workspace_dir=str(project.workspace_dir),
        term=entry.term,
        aliases=aliases,
        definition=entry.definition,
        created_section=False,
        restore_command=glossary_restore_command(
            entry.term, entry.definition, aliases, project.name
        ),
        referenced_by=referenced_by,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedMutationProject:
    name: str
    workspace_dir: Path
    catalog: Any | None
    compiled: Any | None


def _resolve_project(
    project_ref: str | None, *, require_catalog: bool
) -> _ResolvedMutationProject:
    result = editor_glossary_catalog_for_project(project_ref)
    if result.project is None:
        detail = result.diagnostics[0] if result.diagnostics else "no such project"
        raise GlossaryCliError(detail)
    if require_catalog and result.catalog is None:
        if result.diagnostics:
            raise GlossaryCliError("; ".join(result.diagnostics))
        raise GlossaryCliError(f"{result.project.name} has no glossary configured")
    catalog = None if result.catalog is None else result.catalog.catalog
    compiled = None if result.catalog is None else result.catalog.compiled
    return _ResolvedMutationProject(
        name=result.project.name,
        workspace_dir=result.project.workspace_dir,
        catalog=catalog,
        compiled=compiled,
    )


def require_glossary_term_text(term: str) -> str:
    """Validate and normalize a glossary term string shared by all write paths."""
    if "\n" in term or "\r" in term:
        raise GlossaryMutationError("glossary term must be a single-line string")
    cleaned = term.strip()
    if not cleaned:
        raise GlossaryMutationError("glossary term must be a nonblank string")
    if not normalize_glossary_reference(cleaned):
        raise GlossaryMutationError("glossary term must contain more than separators")
    return cleaned


def require_glossary_definition_text(definition: str) -> str:
    """Validate and normalize a glossary definition string shared by all write paths."""
    cleaned = definition.strip()
    if not cleaned:
        raise GlossaryMutationError("glossary definition must be a nonblank string")
    return cleaned


def normalize_glossary_aliases(aliases: Sequence[str]) -> tuple[str, ...]:
    """Validate and normalize glossary aliases shared by all write paths."""
    cleaned: list[str] = []
    for alias in aliases:
        if "\n" in alias or "\r" in alias:
            raise GlossaryMutationError("glossary alias must be a single-line string")
        stripped = alias.strip()
        if stripped:
            cleaned.append(stripped)
    return tuple(cleaned)


def _read_config_text(path: Path) -> tuple[bytes | None, str]:
    data = _read_optional_bytes(path)
    if data is None:
        return None, ""
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GlossaryMutationError(
            f"glossary config is not valid UTF-8: {path}"
        ) from exc


def _read_optional_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def _load_current_entries(text: str) -> tuple[tuple[GlossaryInputEntry, ...], bool]:
    if not text.strip():
        return (), True
    handler = make_yaml()
    try:
        loaded = handler.load(text)
    except Exception as exc:
        raise GlossaryMutationError(
            f"failed to parse project config YAML: {exc}"
        ) from exc
    if loaded is None:
        return (), True
    if not isinstance(loaded, Mapping):
        raise GlossaryMutationError("project config must be a YAML mapping")
    resolution = resolve_glossary_config(loaded)
    if resolution.error is not None:
        raise GlossaryMutationError(resolution.error)
    if not resolution.declared or resolution.node is None:
        return (), True
    if not isinstance(resolution.node, Mapping):
        raise GlossaryMutationError("memory.glossary must be a mapping")
    entries: list[GlossaryInputEntry] = []
    for raw_term, value in resolution.node.items():
        if not isinstance(raw_term, str):
            raise GlossaryMutationError("memory.glossary keys must be strings")
        if not isinstance(value, Mapping):
            raise GlossaryMutationError(f"memory.glossary.{raw_term} must be a mapping")
        definition = value.get("definition")
        if not isinstance(definition, str) or not definition.strip():
            raise GlossaryMutationError(
                f"memory.glossary.{raw_term}.definition must be a nonblank string"
            )
        raw_aliases = value.get("aliases", [])
        if raw_aliases is None:
            alias_values: tuple[str, ...] = ()
        elif not isinstance(raw_aliases, list):
            raise GlossaryMutationError(
                f"memory.glossary.{raw_term}.aliases must be a list"
            )
        else:
            alias_values = tuple(
                alias
                for alias in raw_aliases
                if isinstance(alias, str) and alias.strip()
            )
        entries.append(
            GlossaryInputEntry(
                term=raw_term,
                definition=definition,
                aliases=alias_values,
            )
        )
    return tuple(entries), False


def validate_glossary_candidate(entries: Sequence[GlossaryInputEntry]) -> None:
    """Raise :class:`GlossaryValidationError` when a candidate entry set is invalid."""
    diagnostics = validate_glossary_entries(entries)
    errors = tuple(item for item in diagnostics if item.severity == "error")
    if errors:
        raise GlossaryValidationError(errors)


def _apply_add_to_text(
    text: str, term: str, definition: str, aliases: tuple[str, ...]
) -> str:
    entry_value = _entry_mapping(definition, aliases)
    if not text.strip():
        return set_key(text, (_MEMORY_KEY, _GLOSSARY_KEY, term), entry_value)
    surgical = _try_add_term_surgical(text, term, entry_value)
    if surgical is not None and _glossary_terms_are_sorted(surgical):
        return surgical
    rewritten = _insert_term_sorted_round_trip(text, term, entry_value)
    if _glossary_terms_are_sorted(rewritten):
        return rewritten
    return set_key(text, (_MEMORY_KEY, _GLOSSARY_KEY, term), entry_value)


def _entry_mapping(definition: str, aliases: tuple[str, ...]) -> Any:
    from ruamel.yaml.comments import CommentedMap
    from ruamel.yaml.scalarstring import FoldedScalarString

    entry = CommentedMap()
    if aliases:
        entry["aliases"] = list(aliases)
    entry["definition"] = FoldedScalarString(definition)
    return entry


def _try_add_term_surgical(text: str, term: str, entry_value: Any) -> str | None:
    data = _load_root_mapping(text)
    if data is None:
        return None
    memory = data.get(_MEMORY_KEY)
    if isinstance(memory, MutableMapping) and _GLOSSARY_KEY in memory:
        glossary = memory[_GLOSSARY_KEY]
        if not isinstance(glossary, MutableMapping) or term in glossary:
            return None
        return _try_insert_into_glossary(text, glossary, term, entry_value)
    if isinstance(memory, MutableMapping):
        return _try_insert_glossary_under_memory(text, data, term, entry_value)
    return _try_append_top_level_section(text, term, entry_value)


def _try_insert_into_glossary(
    text: str,
    glossary: MutableMapping[Any, Any],
    term: str,
    entry_value: Any,
) -> str | None:
    lines = text.splitlines(keepends=True)
    location = _sorted_glossary_insert_location(lines, glossary, term)
    if location is None:
        return None
    insert_at, indent = location
    block = _dump_mapping_block({term: entry_value}, indent, _preferred_newline(lines))
    if not block:
        return None
    return _splice_lines(lines, insert_at, block)


def _try_insert_glossary_under_memory(
    text: str,
    data: MutableMapping[Any, Any],
    term: str,
    entry_value: Any,
) -> str | None:
    lines = text.splitlines(keepends=True)
    memory_location = _key_location(data, _MEMORY_KEY)
    if memory_location is None:
        return None
    insert_at = _block_end(lines, memory_location[0], memory_location[1])
    indent = memory_location[1] + 2
    payload = {_GLOSSARY_KEY: {term: entry_value}}
    block = _dump_mapping_block(payload, indent, _preferred_newline(lines))
    if not block:
        return None
    return _splice_lines(lines, insert_at, block)


def _try_append_top_level_section(text: str, term: str, entry_value: Any) -> str | None:
    lines = text.splitlines(keepends=True)
    newline = _preferred_newline(lines)
    payload = {_MEMORY_KEY: {_GLOSSARY_KEY: {term: entry_value}}}
    block = _dump_mapping_block(payload, 0, newline)
    if not block:
        return None
    body = text if text.endswith(("\n", "\r")) or not text else f"{text}{newline}"
    return f"{body}{block}"


def _sorted_glossary_insert_location(
    lines: list[str],
    glossary: MutableMapping[Any, Any],
    term: str,
) -> tuple[int, int] | None:
    term_keys = [key for key in glossary if isinstance(key, str)]
    later = [key for key in term_keys if key > term]
    if later:
        successor = min(later)
        location = _key_location(glossary, successor)
        if location is None:
            return None
        return location[0], location[1]
    earlier = [key for key in term_keys if key < term]
    if earlier:
        predecessor = max(earlier)
        location = _key_location(glossary, predecessor)
        if location is None:
            return None
        return _block_end(lines, location[0], location[1]), location[1]
    location = _key_location(glossary, term_keys[0]) if term_keys else None
    if location is None:
        return None
    return location[0], location[1]


def _insert_term_sorted_round_trip(text: str, term: str, entry_value: Any) -> str:
    from ruamel.yaml.comments import CommentedMap

    handler = make_yaml()
    data = handler.load(text) if text.strip() else None
    if not isinstance(data, MutableMapping):
        data = CommentedMap()
    memory = data.get(_MEMORY_KEY)
    if not isinstance(memory, MutableMapping):
        memory = CommentedMap()
        data[_MEMORY_KEY] = memory
    raw_glossary = memory.get(_GLOSSARY_KEY)
    if isinstance(raw_glossary, CommentedMap):
        glossary = raw_glossary
    elif isinstance(raw_glossary, MutableMapping):
        glossary = CommentedMap()
        glossary.update(raw_glossary)
        memory[_GLOSSARY_KEY] = glossary
    else:
        glossary = CommentedMap()
        memory[_GLOSSARY_KEY] = glossary
    if term in glossary:
        glossary[term] = entry_value
    else:
        insert_at = next(
            (index for index, key in enumerate(glossary) if str(key) > term),
            len(glossary),
        )
        glossary.insert(insert_at, term, entry_value)
    return dump_yaml(handler, data)


def _glossary_terms_are_sorted(text: str) -> bool:
    keys = _glossary_term_keys(text)
    return keys == sorted(keys)


def _glossary_term_keys(text: str) -> list[str]:
    data = _load_root_mapping(text)
    if data is None:
        return []
    memory = data.get(_MEMORY_KEY)
    if not isinstance(memory, MutableMapping):
        return []
    glossary = memory.get(_GLOSSARY_KEY)
    if not isinstance(glossary, MutableMapping):
        return []
    return [str(key) for key in glossary if isinstance(key, str)]


def _dump_mapping_block(mapping: Any, indent: int, newline: str) -> str:
    dumped = dump_yaml(make_yaml(), mapping)
    pad = " " * indent
    lines = [f"{pad}{line}" if line else line for line in dumped.splitlines()]
    if not lines:
        return ""
    return newline.join(lines) + newline


def _splice_lines(lines: list[str], insert_at: int, block: str) -> str:
    newline = _preferred_newline(lines)
    updated = list(lines)
    if insert_at > 0 and updated and not updated[insert_at - 1].endswith(("\n", "\r")):
        updated[insert_at - 1] = f"{updated[insert_at - 1]}{newline}"
    return "".join(updated[:insert_at]) + block + "".join(updated[insert_at:])


def _load_root_mapping(text: str) -> MutableMapping[Any, Any] | None:
    handler = make_yaml()
    try:
        data = handler.load(text) if text.strip() else None
    except Exception:
        return None
    if not isinstance(data, MutableMapping):
        return None
    return data


def _key_location(
    node: MutableMapping[Any, Any], key: str
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


def _block_end(lines: list[str], start_line: int, indent: int) -> int:
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


def _preferred_newline(lines: list[str]) -> str:
    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
    return "\n"


def glossary_restore_command(
    term: str, definition: str, aliases: Sequence[str], project_name: str
) -> str:
    """Build the ``sase glossary add`` command that restores a deleted term."""
    parts = ["sase", "glossary", "add", term, definition]
    for alias in aliases:
        parts.extend(["-a", alias])
    parts.extend(["-p", project_name])
    return " ".join(shlex.quote(part) for part in parts)


def _write_config_atomically(
    path: Path, new_text: str, expected_bytes: bytes | None
) -> None:
    current = _read_optional_bytes(path)
    if current != expected_bytes:
        raise GlossaryConflictError(path)
    created = current is None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            if not created:
                mode = stat.S_IMODE(path.stat().st_mode)
                os.fchmod(stream.fileno(), mode)
            stream.write(new_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if not replaced and temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    _fsync_directory(path.parent)
    clear_config_cache()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "GlossaryConflictError",
    "GlossaryMutationError",
    "GlossaryMutationOutcome",
    "GlossaryValidationError",
    "add_glossary_term",
    "delete_glossary_term",
    "glossary_restore_command",
    "normalize_glossary_aliases",
    "require_glossary_definition_text",
    "require_glossary_term_text",
    "validate_glossary_candidate",
]
