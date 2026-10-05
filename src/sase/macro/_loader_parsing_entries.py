"""Macro entry parsing for config mappings and local macros."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tags import MacroTag

from ._loader_parsing_inputs import parse_inputs_from_front_matter
from .models import (
    InputArg,
    Macro,
    MacroValidationError,
)
from .tags import parse_tags


class LocalMacroNameError(ValueError):
    """Raised when a local macro name does not start with ``_``."""


def parse_macro_entries(entries: dict[str, Any], source_path: str) -> dict[str, Macro]:
    """Parse a dict of macro entries into Macro objects.

    Supports both simple string format and structured dict format:

    Simple format:
        foo: "Content here"

    Structured format (with inputs):
        bar:
            input: {name: word, count: {type: int, default: 0}}
            content: "Hello {{ name }}, count is {{ count }}"

    Args:
        entries: Dictionary mapping macro names to string content or
            structured dicts with input/content keys.
        source_path: Source identifier for the macros (e.g., file path or "config").

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    macros: dict[str, Macro] = {}

    for name, value in entries.items():
        if not isinstance(name, str):
            from .load_issues import record_load_issue

            record_load_issue(
                source_path,
                f"skipped macro entry with non-string name: {name!r}",
                kind="config",
            )
            continue

        if isinstance(value, str):
            # Simple string content (no arguments)
            content = value
            inputs: list[InputArg] = []
            tags: frozenset[MacroTag] = frozenset()
            snippet: str | bool | None = None
            description: str | None = None
            skill: bool | list[str] | None = None
            log_skill_use = True
            local_macros: dict[str, Macro] = {}
        elif isinstance(value, dict):
            # Structured macro with input/content
            content = value.get("content", "")
            if not isinstance(content, str):
                from .load_issues import record_load_issue

                record_load_issue(
                    source_path,
                    f"skipped macro entry {name!r}: content must be a string",
                    kind="config",
                )
                continue
            try:
                inputs = parse_inputs_from_front_matter(
                    value.get("input"),
                    source_path=source_path,
                )
                tags = parse_tags(value.get("tags"))
                snippet = value.get("snippet")
                description = value.get("description")
                skill = value.get("skill")
                log_skill_use = value.get("log_skill_use", True)
                from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

                local_entries = normalize_frontmatter_macros(
                    value,
                    source=source_path,
                )
                local_macros = (
                    parse_local_macro_entries(local_entries, source_path)
                    if local_entries
                    else {}
                )
            except MacroValidationError as exc:
                from .load_issues import record_load_issue

                record_load_issue(source_path, exc, kind="input_type")
                continue
        else:
            from .load_issues import record_load_issue

            record_load_issue(
                source_path,
                f"skipped macro entry {name!r}: value must be a string or mapping",
                kind="config",
            )
            continue

        macro_def = Macro(
            name=name,
            content=content,
            inputs=inputs,
            source_path=source_path,
            tags=tags,
            snippet=snippet,
            description=description,
            skill=skill,
            log_skill_use=log_skill_use,
            local_macros=local_macros,
        )
        if _reject_reserved_memory_namespace(macro_def, source_path):
            continue
        # A skill needs a Markdown file in a canonical skill directory for
        # generation to render from, so a config entry can never be one.
        if _reject_config_skill(macro_def, source_path):
            continue
        macros[name] = macro_def

    return macros


def _reject_config_skill(macro_def: Macro, source_path: str) -> bool:
    """Drop a config-defined entry that declares ``skill:``."""
    if not macro_def.skill:
        return False

    from .loader_skills import config_skill_destination, reject_misplaced_skill

    return reject_misplaced_skill(
        macro_def,
        source=f"{source_path}:{macro_def.name}",
        migrate_to=config_skill_destination(),
    )


def _reject_reserved_memory_namespace(macro_def: Macro, source_path: str) -> bool:
    """Drop a config-defined entry that claims the macro-memory namespace."""
    from .reserved_namespaces import reject_reserved_memory_namespace

    return reject_reserved_memory_namespace(
        macro_def.name,
        source=f"{source_path}:{macro_def.name}",
    )


def _validate_local_macro_names(macros: dict[str, Macro]) -> None:
    """Raise if any local macro name does not start with ``_``."""
    for name in macros:
        if not name.startswith("_"):
            raise LocalMacroNameError(
                f"Local macro_def '{name}' must start with '_' (e.g. '_{name}')"
            )


def parse_local_macro_entries(
    entries: dict[str, Any], source_path: str
) -> dict[str, Macro]:
    """Parse local macro entries and enforce local-name scoping rules."""
    macros = parse_macro_entries(entries, source_path)
    _validate_local_macro_names(macros)
    return macros
