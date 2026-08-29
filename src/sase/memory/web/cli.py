"""CLI handlers for ``sase memory web list``/``show``.

``show`` is the filterable *index* for one web and never prints strand bodies. Reading strand
content is ``sase memory show``/``read`` with a ``web:keyword`` selector.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Literal

from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.web.closure import resolve_strand_closure
from sase.memory.web.lookup import normalize_memory_web_reference
from sase.memory.web.models import MemoryStrand, ScopedMemoryWeb
from sase.memory.web.read_context import discover_scoped_memory_webs

_Format = Literal["json", "names", "table"]
_SUMMARY_WIDTH = 72


def handle_memory_web_list_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print every discovered memory web for a project."""
    try:
        project_root, home_root = _resolve_roots(getattr(args, "project", None))
    except MemoryCliProjectError as exc:
        print(f"sase memory web list: {exc}", file=sys.stderr)
        sys.exit(1)

    scoped_webs = discover_scoped_memory_webs(project_root, home_root)
    output_format: _Format = getattr(args, "format", "table")

    if output_format == "json":
        payload = {
            "webs": [
                _web_summary_json(
                    scoped, project_root=project_root, home_root=home_root
                )
                for scoped in scoped_webs
            ]
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if output_format == "names":
        for scoped in scoped_webs:
            print(scoped.slug)
        return

    target = console or Console()
    target.print(
        _list_table(scoped_webs, project_root=project_root, home_root=home_root)
    )


def handle_memory_web_show_command(
    args: argparse.Namespace, *, console: Console | None = None
) -> None:
    """Print one web's filterable strand index.

    This is the index (keyword, aliases, mention-reference count, summary),
    not the content — use ``sase memory show <web>:<keyword>`` to read a
    strand's body.
    """
    try:
        project_root, home_root = _resolve_roots(getattr(args, "project", None))
    except MemoryCliProjectError as exc:
        print(f"sase memory web show: {exc}", file=sys.stderr)
        sys.exit(1)

    scoped_webs = discover_scoped_memory_webs(project_root, home_root)
    by_slug = {scoped.slug: scoped for scoped in scoped_webs}
    web_slug = args.web
    scoped = by_slug.get(web_slug)
    if scoped is None:
        print(f"sase memory web show: unknown memory web: {web_slug}", file=sys.stderr)
        sys.exit(1)

    pattern = getattr(args, "pattern", None)
    include_bodies = getattr(args, "bodies", False)
    strands = _ordered(_filter_strands(scoped.strands, pattern, include_bodies))
    output_format: _Format = getattr(args, "format", "table")

    if output_format == "json":
        payload = _web_show_json(scoped, strands, pattern=pattern)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if not strands:
        print(_no_match_message(pattern))
        return

    if output_format == "names":
        for strand in strands:
            print(strand.keyword)
        return

    target = console or Console()
    target.print(_web_show_table(scoped, strands))


def _resolve_roots(project_ref: str | None) -> tuple[Path, Path]:
    resolved = resolve_memory_cli_project(project_ref)
    project_root = resolved.project_root if resolved is not None else Path.cwd()
    return project_root, Path.home()


def _filter_strands(
    strands: tuple[MemoryStrand, ...], pattern: str | None, include_bodies: bool
) -> tuple[MemoryStrand, ...]:
    if not pattern:
        return strands
    needle = pattern.casefold()
    matched: list[MemoryStrand] = []
    for strand in strands:
        haystacks = [strand.keyword, *strand.aliases]
        if include_bodies:
            haystacks.append(strand.body)
        if any(needle in haystack.casefold() for haystack in haystacks):
            matched.append(strand)
    return tuple(matched)


def _web_scope(
    scoped: ScopedMemoryWeb, *, project_root: Path, home_root: Path
) -> Literal["project", "home"]:
    root = scoped.web.root.resolve(strict=False)
    if root == home_root.resolve(strict=False) and root != project_root.resolve(
        strict=False
    ):
        return "home"
    return "project"


def _web_summary_json(
    scoped: ScopedMemoryWeb, *, project_root: Path, home_root: Path
) -> dict[str, object]:
    return {
        "web": scoped.slug,
        "scope": _web_scope(scoped, project_root=project_root, home_root=home_root),
        "strand_count": len(scoped.strands),
        "description": scoped.web.description,
    }


def _list_table(
    scoped_webs: tuple[ScopedMemoryWeb, ...], *, project_root: Path, home_root: Path
) -> Group:
    if not scoped_webs:
        return Group(Text("no memory webs found", style="dim"))

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("Web")
    table.add_column("Scope", no_wrap=True)
    table.add_column("Strands", justify="right", no_wrap=True)
    table.add_column("Description")
    for scoped in scoped_webs:
        table.add_row(
            scoped.slug,
            _web_scope(scoped, project_root=project_root, home_root=home_root),
            str(len(scoped.strands)),
            scoped.web.description or "",
        )
    return Group(table)


def _reference_slugs(scoped: ScopedMemoryWeb, strand: MemoryStrand) -> tuple[str, ...]:
    merged_web = replace(scoped.web, strands=scoped.strands)
    closure, strand_by_index = resolve_strand_closure(
        merged_web, scoped.strands, (strand,), depth=1
    )
    return tuple(
        strand_by_index[node.entry.index].slug
        for node in closure.nodes
        if node.origin == "related"
    )


def _web_show_table(
    scoped: ScopedMemoryWeb, strands: tuple[MemoryStrand, ...]
) -> Table:
    table = Table(
        title=Text(f"MEMORY WEB  {scoped.slug}", style="bold cyan"),
        caption=f"{len(strands)} {scoped.web.strand_noun}"
        f"{'s' if len(strands) != 1 else ''}",
        show_header=True,
        header_style="bold",
    )
    table.add_column("Keyword")
    table.add_column("Slug")
    table.add_column("Aliases")
    table.add_column("Refs", justify="right", no_wrap=True)
    table.add_column("Summary")
    for strand in strands:
        table.add_row(
            strand.keyword,
            strand.slug,
            " · ".join(strand.aliases),
            str(len(_reference_slugs(scoped, strand))),
            _first_sentence(strand.summary or strand.body),
        )
    return table


def _web_show_json(
    scoped: ScopedMemoryWeb, strands: tuple[MemoryStrand, ...], *, pattern: str | None
) -> dict[str, object]:
    return {
        "web": scoped.slug,
        "pattern": pattern,
        "strands": [
            {
                "slug": strand.slug,
                "keyword": strand.keyword,
                "aliases": list(strand.aliases),
                "summary": strand.summary,
                "reference_slugs": list(_reference_slugs(scoped, strand)),
            }
            for strand in strands
        ],
    }


def _first_sentence(text: str) -> str:
    one_line = " ".join(text.split())
    period = one_line.find(". ")
    sentence = one_line if period == -1 else one_line[: period + 1]
    if len(sentence) <= _SUMMARY_WIDTH:
        return sentence
    return sentence[: _SUMMARY_WIDTH - 3].rstrip() + "..."


def _no_match_message(pattern: str | None) -> str:
    if pattern:
        return f"no strands matched: {pattern}"
    return "no strands matched"


def _ordered(strands: tuple[MemoryStrand, ...]) -> tuple[MemoryStrand, ...]:
    return tuple(
        sorted(
            strands, key=lambda strand: normalize_memory_web_reference(strand.keyword)
        )
    )


__all__ = [
    "handle_memory_web_list_command",
    "handle_memory_web_show_command",
]
