"""Project-local glossary term extraction for generated memory notes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.glossary_facade import (
    GlossaryInputEntry,
    build_glossary_catalog,
    validate_glossary_entries,
)
from sase.glossary_config import GLOSSARY_CONFIG_KEY, resolve_glossary_config
from sase.memory.web.catalog import (
    GLOSSARY_WEB_SLUG,
    find_memory_web,
    glossary_dual_source_diagnostic,
)
from sase.project_management import load_local_config


@dataclass(frozen=True)
class ProjectGlossaryTerms:
    """Ordered project glossary terms and their display aliases."""

    terms: tuple[tuple[str, tuple[str, ...]], ...]


def load_project_glossary_terms(
    config_path: Path, root: Path
) -> tuple[ProjectGlossaryTerms | None, tuple[str, ...]]:
    """Load, validate, and return the project-local glossary's terms.

    Returns ``(None, ())`` when a ``glossary`` memory web owns the glossary
    for *root* instead: the web's own roster region already renders through
    the memory-web root plan, so the generated note must not also be
    produced.
    """
    loaded = load_local_config(config_path)
    if not loaded.valid:
        return None, (loaded.error or f"{config_path}: invalid configuration",)
    resolution = resolve_glossary_config(loaded.config)
    if resolution.error is not None:
        return None, (f"{config_path}: {resolution.error}",)

    glossary_web = find_memory_web(root, GLOSSARY_WEB_SLUG)
    dual_source = glossary_dual_source_diagnostic(
        has_web=glossary_web is not None,
        config_declared=resolution.declared,
    )
    if dual_source is not None:
        return None, (f"{config_path}: {dual_source}",)
    if glossary_web is not None:
        return None, ()

    if not resolution.declared or resolution.node is None:
        return None, ()
    entries, shape_errors = _glossary_entries(
        config_path,
        resolution.node,
        display_path=resolution.display_path,
    )
    if shape_errors:
        return None, shape_errors
    if not entries:
        return None, ()
    try:
        diagnostics = validate_glossary_entries(entries)
    except (AttributeError, ImportError) as exc:
        return None, (f"{config_path}: failed to validate glossary: {exc}",)
    if diagnostics:
        return None, tuple(
            f"{config_path}: "
            f"{_diagnostic_path(diagnostic.path, resolution.display_path)}: "
            f"{diagnostic.message}"
            for diagnostic in diagnostics
            if diagnostic.severity == "error"
        )
    try:
        catalog = build_glossary_catalog(entries)
    except (AttributeError, ImportError, ValueError) as exc:
        return None, (f"{config_path}: failed to build glossary catalog: {exc}",)
    return (
        ProjectGlossaryTerms(
            terms=tuple(
                (entry.term, entry.display_aliases) for entry in catalog.entries
            )
        ),
        (),
    )


def _glossary_entries(
    config_path: Path, raw: Any, *, display_path: str
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
            )
        )
    return tuple(entries), tuple(errors)


def _diagnostic_path(path: str | None, display_path: str) -> str:
    if not path:
        return display_path
    if path == GLOSSARY_CONFIG_KEY:
        return display_path
    if path.startswith(f"{GLOSSARY_CONFIG_KEY}."):
        return f"{display_path}{path.removeprefix(GLOSSARY_CONFIG_KEY)}"
    return path


def _path_component(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    return repr(value)


def _has_newline(value: str) -> bool:
    return "\n" in value or "\r" in value
