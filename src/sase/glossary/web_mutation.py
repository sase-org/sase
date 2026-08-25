"""Strand-file glossary add/delete for projects with a migrated glossary web.

Mirrors :mod:`sase.glossary.mutation`'s config-backed add/delete engine, but
writes and deletes ``sase/memory/glossary/<slug>.md`` strand files instead of
editing ``memory.glossary`` in the project config. Both engines share the same
validation primitives and produce the same :class:`GlossaryMutationOutcome`
shape, so :mod:`sase.glossary.cli_write`'s rendering and post-write
regeneration need no web-specific branch.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from rich.console import Console
import yaml  # type: ignore[import-untyped]

from sase.core.glossary_facade import GlossaryInputEntry
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.cli_write import (
    GlossaryWriteFormat,
    emit_glossary_write_outcome,
    exit_glossary_write_error,
    write_error_types,
)
from sase.glossary.mutation import (
    GlossaryMutationError,
    GlossaryMutationOutcome,
    glossary_restore_command,
    normalize_glossary_aliases,
    require_glossary_definition_text,
    require_glossary_term_text,
    validate_glossary_candidate,
)
from sase.glossary.relations import glossary_reverse_references
from sase.glossary.resolution import (
    GlossaryLookupError,
    normalize_glossary_reference,
    resolve_glossary_closure,
)
from sase.memory.web.catalog import memory_web_glossary_entries
from sase.memory.web.models import MemoryStrand, MemoryWeb
from sase.xprompt.glossary_catalog import editor_glossary_catalog_for_project


def add_glossary_strand(
    project_ref: str | None,
    web: MemoryWeb,
    term: str,
    definition: str,
    aliases: Sequence[str] = (),
) -> GlossaryMutationOutcome:
    """Write a new strand file into *web* after the same Rust validation."""
    cleaned_term = require_glossary_term_text(term)
    cleaned_definition = require_glossary_definition_text(definition)
    cleaned_aliases = normalize_glossary_aliases(aliases)
    project = _resolve_project(project_ref)

    slug = _strand_slug(cleaned_term)
    strand_path = web.memory_root / web.slug / f"{slug}.md"
    if strand_path.exists() or any(strand.slug == slug for strand in web.strands):
        raise GlossaryMutationError(f"glossary strand slug already exists: {slug}")

    candidate = (
        *memory_web_glossary_entries(web),
        GlossaryInputEntry(
            term=cleaned_term,
            definition=cleaned_definition,
            aliases=cleaned_aliases,
        ),
    )
    validate_glossary_candidate(candidate)

    strand_path.parent.mkdir(parents=True, exist_ok=True)
    strand_path.write_text(
        _render_strand_text(cleaned_term, cleaned_definition, cleaned_aliases),
        encoding="utf-8",
    )

    return GlossaryMutationOutcome(
        project_name=project.name,
        config_path=str(strand_path),
        workspace_dir=str(project.workspace_dir),
        term=cleaned_term,
        aliases=cleaned_aliases,
        definition=cleaned_definition,
        created_section=False,
        restore_command=glossary_restore_command(
            cleaned_term, cleaned_definition, cleaned_aliases, project.name
        ),
        referenced_by=(),
    )


def delete_glossary_strand(
    project_ref: str | None,
    web: MemoryWeb,
    reference: str,
    *,
    dry_run: bool = False,
) -> GlossaryMutationOutcome:
    """Remove the strand file resolved from *reference* after validation.

    When *dry_run* is true, resolve, validate, and return the outcome without
    deleting the strand file.
    """
    project = _resolve_project(project_ref)
    catalog = project.catalog
    compiled = project.compiled
    if catalog is None or compiled is None:
        raise GlossaryCliError(f"{project.name} has no glossary configured")
    entry = resolve_glossary_closure(catalog, compiled, (reference,), depth=0).roots[0]
    referenced_by = tuple(
        glossary_reverse_references(catalog, compiled).get(entry.index, ())
    )

    strand = _find_strand_by_term(web, entry.term)
    if strand is None:
        raise GlossaryLookupError(reference)

    remaining = tuple(
        item
        for item in memory_web_glossary_entries(web)
        if normalize_glossary_reference(item.term)
        != normalize_glossary_reference(entry.term)
    )
    validate_glossary_candidate(remaining)

    if not dry_run:
        strand.path.unlink()

    aliases = entry.configured_aliases
    return GlossaryMutationOutcome(
        project_name=project.name,
        config_path=str(strand.path),
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


def handle_glossary_add_web_command(
    args: argparse.Namespace, web: MemoryWeb, *, console: Console | None = None
) -> None:
    """Add a glossary term to a project's glossary web and print the outcome."""
    project_ref = getattr(args, "project", None)
    try:
        outcome = add_glossary_strand(
            project_ref,
            web,
            args.term,
            args.definition,
            aliases=tuple(getattr(args, "alias", None) or ()),
        )
    except write_error_types() as exc:
        exit_glossary_write_error("add", exc, project_ref=project_ref)

    emit_glossary_write_outcome(
        outcome,
        operation="add",
        output_format=cast(GlossaryWriteFormat, getattr(args, "format", "rich")),
        dry_run=False,
        no_init=bool(getattr(args, "no_init", False)),
        command="add",
        console=console,
    )


def handle_glossary_del_web_command(
    args: argparse.Namespace, web: MemoryWeb, *, console: Console | None = None
) -> None:
    """Delete a glossary strand (or preview the delete) and print the outcome."""
    project_ref = getattr(args, "project", None)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        outcome = delete_glossary_strand(project_ref, web, args.term, dry_run=dry_run)
    except write_error_types() as exc:
        exit_glossary_write_error("del", exc, project_ref=project_ref)

    emit_glossary_write_outcome(
        outcome,
        operation="del",
        output_format=cast(GlossaryWriteFormat, getattr(args, "format", "rich")),
        dry_run=dry_run,
        no_init=bool(getattr(args, "no_init", False)),
        command="del",
        console=console,
    )


@dataclass(frozen=True, slots=True)
class _ResolvedWebMutationProject:
    """The project resolved for a web-backed glossary mutation."""

    name: str
    workspace_dir: Path
    catalog: Any | None
    compiled: Any | None


def _resolve_project(project_ref: str | None) -> _ResolvedWebMutationProject:
    result = editor_glossary_catalog_for_project(project_ref)
    if result.project is None:
        detail = result.diagnostics[0] if result.diagnostics else "no such project"
        raise GlossaryCliError(detail)
    catalog = None if result.catalog is None else result.catalog.catalog
    compiled = None if result.catalog is None else result.catalog.compiled
    return _ResolvedWebMutationProject(
        name=result.project.name,
        workspace_dir=result.project.workspace_dir,
        catalog=catalog,
        compiled=compiled,
    )


def _find_strand_by_term(web: MemoryWeb, term: str) -> MemoryStrand | None:
    for strand in web.strands:
        if strand.keyword == term:
            return strand
    return None


def _strand_slug(term: str) -> str:
    return normalize_glossary_reference(term).replace(" ", "-")


def _render_strand_text(term: str, definition: str, aliases: tuple[str, ...]) -> str:
    frontmatter: dict[str, object] = {"keyword": term}
    if aliases:
        frontmatter["aliases"] = list(aliases)
    header = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False)
    body = definition if definition.endswith("\n") else f"{definition}\n"
    return f"---\n{header}---\n{body}"


__all__ = [
    "add_glossary_strand",
    "delete_glossary_strand",
    "handle_glossary_add_web_command",
    "handle_glossary_del_web_command",
]
