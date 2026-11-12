"""Shared single-file macro reading used by every source loader.

This private module holds the helpers more than one ``loader_sources_*``
module needs under public names: namespacing, local-macro parsing, reading
one Markdown file, and iterating one ordinary macro directory. Aggregating
loaders import these instead of duplicating them.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .load_issues import record_load_issue
from .loader_parsing import (
    parse_inputs_from_front_matter,
    parse_local_macro_entries,
    parse_yaml_front_matter_with_error,
)
from .loader_skills import (
    reject_misplaced_skill,
    skill_destination_for_macro_dir,
)
from .models import InputArg, Macro, MacroValidationError
from .reserved_namespaces import reject_reserved_memory_namespace
from .tags import parse_tags


def namespace_macro(project: str, xp: Macro) -> Macro:
    """Return a copy of *xp* with its name prefixed by ``{project}/``.

    Skills are namespaced by :func:`sase.content_layout.skill_reference_name`
    instead, but ``skill_name`` is carried through so a copy never loses the
    provider-visible name.
    """
    namespaced_name = f"{project}/{xp.name}"
    return Macro(
        name=namespaced_name,
        content=xp.content,
        inputs=xp.inputs,
        source_path=xp.source_path,
        tags=xp.tags,
        snippet=xp.snippet,
        description=xp.description,
        skill=xp.skill,
        skill_name=xp.skill_name,
        log_skill_use=xp.log_skill_use,
        local_macros=xp.local_macros,
        memory_type=xp.memory_type,
        discovery_rank=xp.discovery_rank,
        trust=xp.trust,
    )


def parse_markdown_local_macros(
    front_matter: dict[str, Any] | None, source_path: str
) -> dict[str, Macro]:
    """Parse embedded local macros from Markdown front matter."""
    if not front_matter:
        return {}
    from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

    macros_data = normalize_frontmatter_macros(front_matter, source=source_path)
    if not macros_data:
        return {}
    return parse_local_macro_entries(macros_data, source_path)


def load_macro_from_file(file_path: Path) -> Macro | None:
    """Load a single macro from a markdown file.

    Args:
        file_path: Path to the .md file.

    Returns:
        Macro object if successfully loaded, None otherwise.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        record_load_issue(file_path, exc, kind="frontmatter")
        return None

    front_matter, body, frontmatter_error = parse_yaml_front_matter_with_error(content)
    if frontmatter_error is not None:
        record_load_issue(
            file_path,
            f"invalid YAML frontmatter (treated as plain body): {frontmatter_error}",
            kind="frontmatter",
        )

    # Get name from front matter or fallback to filename
    if front_matter and "name" in front_matter:
        name = str(front_matter["name"])
    else:
        name = file_path.stem  # Filename without extension

    # Parse inputs if present
    inputs: list[InputArg] = []
    try:
        if front_matter and "input" in front_matter:
            inputs = parse_inputs_from_front_matter(
                front_matter["input"],
                source_path=str(file_path),
            )
        local_macros = parse_markdown_local_macros(front_matter, str(file_path))
    except MacroValidationError as exc:
        record_load_issue(file_path, exc, kind="input_type")
        return None

    # Parse tags if present
    tags = parse_tags(front_matter.get("tags")) if front_matter else frozenset()

    # Parse snippet field if present
    snippet = front_matter.get("snippet") if front_matter else None

    # Parse description and skill fields if present
    description = front_matter.get("description") if front_matter else None
    skill = front_matter.get("skill") if front_matter else None
    log_skill_use = front_matter.get("log_skill_use", True) if front_matter else True

    if reject_reserved_memory_namespace(name, source=file_path):
        return None

    return Macro(
        name=name,
        content=body,
        inputs=inputs,
        source_path=str(file_path),
        tags=tags,
        snippet=snippet,
        description=description,
        skill=skill,
        log_skill_use=log_skill_use,
        local_macros=local_macros,
    )


def load_ordinary_macros_from_dir(directory: Path) -> Iterator[Macro]:
    """Yield loadable non-skill definitions from an ordinary macro dir.

    A ``skill:`` declaration here is rejected with a migration diagnostic
    naming the scope's canonical ``sase/skills/`` directory, so a misplaced
    skill is reported rather than loaded under its bare name.
    """
    destination = skill_destination_for_macro_dir(directory)
    for md_file in sorted(directory.glob("*.md")):
        if not md_file.is_file():
            continue
        macro_def = load_macro_from_file(md_file)
        if macro_def is None:
            continue
        if reject_reserved_memory_namespace(macro_def.name, source=md_file):
            continue
        if reject_misplaced_skill(macro_def, source=md_file, migrate_to=destination):
            continue
        yield macro_def
