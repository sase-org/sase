"""Read a project config's glossary node and shape it into input entries.

Everything here works on the raw round-trip YAML: reading the file, checking
the declared shape of each term, and turning native validation diagnostics into
config-relative error strings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.config._edit_yaml_io import make_yaml
from sase.core.glossary_facade import (
    GlossaryDiagnostic,
    GlossaryInputEntry,
    GlossarySource,
    validate_glossary_entries,
)
from sase.glossary_config import GLOSSARY_CONFIG_KEY
from sase.xprompt._glossary_catalog_ranges import key_range, value_range


def load_round_trip_mapping(
    config_path: Path,
) -> tuple[Mapping[Any, Any] | None, tuple[str, ...]]:
    """Load *config_path* as a round-trip mapping, or report why it could not be."""

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


def read_config_lines(path: Path) -> list[str]:
    """Return *path*'s lines, or an empty list when it cannot be read."""

    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def parse_glossary_entries(
    config_path: Path,
    raw: Any,
    lines: Sequence[str],
    *,
    config_key_path: tuple[str, ...],
    display_path: str,
) -> tuple[tuple[GlossaryInputEntry, ...], tuple[str, ...]]:
    """Shape the declared glossary node into entries plus shape errors."""

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


def validation_diagnostics(
    config_path: Path,
    entries: Sequence[GlossaryInputEntry],
    *,
    display_path: str,
) -> tuple[str, ...]:
    """Return the error-severity diagnostics native validation reports."""

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


def _glossary_source(
    config_path: Path,
    glossary_node: Mapping[Any, Any],
    term: str,
    entry_node: Mapping[Any, Any],
    lines: Sequence[str],
    *,
    config_key_path: tuple[str, ...],
) -> GlossarySource:
    term_range = key_range(glossary_node, term)
    definition_range = value_range(entry_node, "definition", lines)
    aliases_range = value_range(entry_node, "aliases", lines)
    return GlossarySource(
        config_path=str(config_path),
        config_key_path=(*config_key_path, term),
        term_range=term_range,
        definition_range=definition_range,
        aliases_range=aliases_range,
    )


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


def _path_component(value: Any) -> str:
    if isinstance(value, str) and value:
        return value
    return repr(value)


def _has_newline(value: str) -> bool:
    return "\n" in value or "\r" in value
