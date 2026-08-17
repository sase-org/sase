"""CLI handler for ``sase glossary list``."""

from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import SECTION_COLOR
from sase.core.glossary_facade import GlossaryEntry
from sase.glossary.cli_common import (
    GlossaryCliError,
    ResolvedGlossaryProject,
    resolve_glossary_cli_project,
)
from sase.glossary.resolution import resolve_glossary_closure

_SUMMARY_WIDTH = 72


def handle_glossary_list_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """List glossary terms for a project, filtered and formatted per *args*."""
    try:
        resolved = resolve_glossary_cli_project(getattr(args, "project", None))
    except GlossaryCliError as exc:
        print(f"sase glossary list: {exc}", file=sys.stderr)
        sys.exit(1)

    pattern = getattr(args, "pattern", None)
    include_definitions = getattr(args, "definitions", False)
    output_format = getattr(args, "format", "table")

    entries = _filter_entries(
        resolved.catalog.entries,
        pattern=pattern,
        include_definitions=include_definitions,
    )

    if output_format == "json":
        payload = _build_json_payload(resolved, entries, pattern=pattern)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if not entries:
        print(_no_match_message(pattern))
        return

    if output_format == "names":
        for entry in entries:
            print(entry.term)
        return

    target = console or Console()
    target.print(_build_table(resolved, entries))


def _filter_entries(
    entries: tuple[GlossaryEntry, ...],
    *,
    pattern: str | None,
    include_definitions: bool,
) -> tuple[GlossaryEntry, ...]:
    if not pattern:
        return entries
    needle = pattern.casefold()
    matched: list[GlossaryEntry] = []
    for entry in entries:
        haystacks = [entry.term, *entry.display_aliases]
        if include_definitions:
            haystacks.append(entry.definition)
        if any(needle in haystack.casefold() for haystack in haystacks):
            matched.append(entry)
    return tuple(matched)


def _reference_terms(
    resolved: ResolvedGlossaryProject, entry: GlossaryEntry
) -> tuple[str, ...]:
    closure = resolve_glossary_closure(
        resolved.catalog, resolved.compiled, (entry,), depth=1
    )
    return tuple(node.entry.term for node in closure.nodes if node.origin == "related")


def _build_table(
    resolved: ResolvedGlossaryProject, entries: tuple[GlossaryEntry, ...]
) -> Table:
    table = Table(
        title=Text(f"GLOSSARY  {resolved.project_name}", style=f"bold {SECTION_COLOR}"),
        caption=f"{len(entries)} term{'s' if len(entries) != 1 else ''}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Term")
    table.add_column("Aliases")
    table.add_column("Refs", justify="right", no_wrap=True)
    table.add_column("Summary")

    for entry in entries:
        table.add_row(
            entry.term,
            " · ".join(entry.display_aliases),
            str(len(_reference_terms(resolved, entry))),
            _first_sentence(entry.definition),
        )
    return table


def _build_json_payload(
    resolved: ResolvedGlossaryProject,
    entries: tuple[GlossaryEntry, ...],
    *,
    pattern: str | None,
) -> dict[str, object]:
    return {
        "project": resolved.project_name,
        "pattern": pattern,
        "terms": [
            {
                "term": entry.term,
                "aliases": list(entry.display_aliases),
                "definition": entry.definition,
                "reference_terms": list(_reference_terms(resolved, entry)),
                "source": entry.source,
            }
            for entry in entries
        ],
    }


def _first_sentence(definition: str) -> str:
    one_line = " ".join(definition.split())
    period = one_line.find(". ")
    sentence = one_line if period == -1 else one_line[: period + 1]
    if len(sentence) <= _SUMMARY_WIDTH:
        return sentence
    return sentence[: _SUMMARY_WIDTH - 3].rstrip() + "..."


def _no_match_message(pattern: str | None) -> str:
    if pattern:
        return f"no terms matched: {pattern}"
    return "no terms matched"


__all__ = ["handle_glossary_list_command"]
