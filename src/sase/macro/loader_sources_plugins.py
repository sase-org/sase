"""Plugin-package macro loaders (``macros/`` resource directories)."""

import importlib.resources
import logging
from collections.abc import Iterator
from typing import Any

from sase.main.plugin_discovery import (
    discover_macro_plugin_modules,
    macro_plugin_definition_dirname,
    macro_plugins_disabled,
)

from ._loader_sources_common import parse_markdown_local_macros
from .discovery_order import RANK_PLUGIN
from .load_issues import record_load_issue
from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_yaml_front_matter,
)
from .loader_skills import (
    plugin_skill_destination,
    reject_misplaced_skill,
)
from .models import InputArg, Macro, MacroValidationError
from .reserved_namespaces import reject_reserved_memory_namespace
from .tags import parse_tags

log = logging.getLogger(__name__)


def load_plugin_markdown_macros(
    module: Any, resource_dir: str
) -> Iterator[tuple[str, Macro]]:
    """Yield ``(source, macro)`` for one plugin resource directory.

    Skill placement is *not* applied here: ``macros/`` and ``skills/`` are
    sibling resource directories parsed identically, and each caller applies
    the rule for the directory it asked for.
    """
    try:
        resource = importlib.resources.files(module).joinpath(resource_dir)
    except (TypeError, AttributeError):
        return

    try:
        entries = list(resource.iterdir())  # type: ignore[union-attr]
    except (FileNotFoundError, OSError, TypeError, NotADirectoryError):
        return

    for entry in sorted(entries, key=lambda item: item.name):  # type: ignore[union-attr]
        if not entry.name.endswith(".md"):  # type: ignore[union-attr]
            continue
        try:
            text = entry.read_text(encoding="utf-8")  # type: ignore[union-attr]
        except (OSError, UnicodeDecodeError):
            continue

        front_matter, body = parse_yaml_front_matter(text)
        name = entry.name.removesuffix(".md")  # type: ignore[union-attr]
        if front_matter and "name" in front_matter:
            name = str(front_matter["name"])

        source = f"plugin:{module.__name__}/{entry.name}"  # type: ignore[union-attr]
        try:
            inputs: list[InputArg] = []
            if front_matter and "input" in front_matter:
                inputs = parse_inputs_from_front_matter(
                    front_matter["input"],
                    source_path=source,
                )
        except MacroValidationError as exc:
            record_load_issue(source, exc, kind="input_type")
            continue

        tags = parse_tags(front_matter.get("tags")) if front_matter else frozenset()
        yield (
            source,
            Macro(
                name=name,
                content=body,
                inputs=inputs,
                source_path=source,
                tags=tags,
                snippet=front_matter.get("snippet") if front_matter else None,
                description=(front_matter.get("description") if front_matter else None),
                skill=front_matter.get("skill") if front_matter else None,
                log_skill_use=(
                    front_matter.get("log_skill_use", True) if front_matter else True
                ),
                local_macros=parse_markdown_local_macros(front_matter, source),
            ),
        )


def load_macros_from_plugins() -> dict[str, Macro]:
    """Load macros from plugin packages via ``sase_macros`` entry points.

    Each entry point should reference a module whose package contains an
    ``macros/`` resource directory with ``.md`` files; a retired packaged
    directory is always accepted as an alias. Plugin skills live in
    a sibling ``skills/`` resource directory instead, so a ``skill:``
    declaration here is rejected with that migration destination.

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    if macro_plugins_disabled():
        return {}

    macros: dict[str, Macro] = {}
    for module in discover_macro_plugin_modules():
        resource_dir = macro_plugin_definition_dirname(module)
        if resource_dir is None:
            log.debug(
                "Skipping plugin %s without a macro resource directory",
                getattr(module, "__name__", module),
            )
            continue
        for source, macro_def in load_plugin_markdown_macros(module, resource_dir):
            if reject_reserved_memory_namespace(macro_def.name, source=source):
                continue
            if reject_misplaced_skill(
                macro_def,
                source=source,
                migrate_to=plugin_skill_destination(),
            ):
                continue
            macro_def.discovery_rank = RANK_PLUGIN
            macros[macro_def.name] = macro_def

    return macros
