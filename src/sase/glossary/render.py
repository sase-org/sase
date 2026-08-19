"""Shared rendering for ``sase glossary show``/``read``/``all`` output.

``show`` and ``read`` resolve a :class:`~sase.glossary.resolution.GlossaryClosure`
through identical code and must print identical output for identical
arguments, so both route through :func:`render_glossary_closure`.
``all`` prints the same closure over every catalog entry via
:func:`render_glossary_catalog`.
"""

from __future__ import annotations

from collections.abc import Mapping
from io import StringIO
import json
import sys
from typing import Literal, cast

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import SECTION_COLOR
from sase.glossary.resolution import (
    GlossaryClosure,
    GlossaryClosureNode,
    GlossaryReferrer,
)

GlossaryShowFormat = Literal["json", "markdown", "rich"]
_ColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"]

_INDENT_STEP = 2
_MAX_INDENT_DEPTH = 3
_ACCENT = SECTION_COLOR
_MARKDOWN_MAX_HEADING_LEVEL = 6
_AUDIT_HINT = (
    'Not an audited read — agents must use: sase glossary read <term> -r "<why>"'
)
_EMPTY_CATALOG = "no glossary terms configured for {project}"


def render_glossary_closure(
    closure: GlossaryClosure,
    *,
    project_name: str,
    output_format: GlossaryShowFormat,
    console: Console | None = None,
) -> None:
    """Print *closure* to stdout in the requested format."""
    if output_format == "json":
        payload = _glossary_closure_json_payload(closure, project_name=project_name)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if output_format == "markdown":
        sys.stdout.write(glossary_closure_markdown(closure, project_name=project_name))
        return

    target = console or Console()
    _print_rich_without_trailing_whitespace(
        target,
        _glossary_closure_renderable(closure, project_name=project_name),
    )


def _print_rich_without_trailing_whitespace(
    console: Console, renderable: RenderableType
) -> None:
    """Print *renderable* with wrap-padding stripped from every line.

    Rich wraps long definition ``Text`` to the console width and pads each
    wrapped line out to that width. Those spaces are invisible in a terminal
    and waste tokens in captured agent output.
    """
    buffer = StringIO()
    capture = Console(
        file=buffer,
        width=console.width,
        force_terminal=console.is_terminal,
        # Rich types the property as str | None, the constructor as this Literal.
        color_system=cast(_ColorSystem | None, console.color_system),
        highlight=False,
        markup=False,
    )
    capture.print(renderable)
    console.file.write(_rstrip_output_lines(buffer.getvalue()))


def _rstrip_output_lines(text: str) -> str:
    if not text:
        return text
    stripped = "\n".join(line.rstrip() for line in text.splitlines())
    if text.endswith("\n"):
        return stripped + "\n"
    return stripped


# --- rich ---------------------------------------------------------------


def _glossary_closure_renderable(
    closure: GlossaryClosure, *, project_name: str
) -> Group:
    """Build the Rich tree rendering for one glossary closure."""
    printed_indices = {node.entry.index for node in closure.nodes}
    requested = sum(1 for node in closure.nodes if node.origin == "requested")
    related = len(closure.nodes) - requested

    blocks: list[RenderableType] = [
        _build_header(
            project_name, total=len(closure.nodes), requested=requested, related=related
        ),
    ]
    if closure.requested_references > len(closure.roots):
        blocks.append(
            Text(
                f"{closure.requested_references} references resolved to "
                f"{len(closure.roots)} terms (duplicates and aliases collapsed)",
                style="dim",
            )
        )
    blocks.append(Text(""))
    for node in closure.nodes:
        blocks.extend(_build_node_blocks(node, printed_indices=printed_indices))
        blocks.append(Text(""))
    blocks.extend(
        _build_footer(
            related=related,
            truncated=closure.truncated,
            depth_limit=closure.depth_limit,
        )
    )
    return Group(*blocks)


def _header_grid(project_name: str, right: str) -> RenderableType:
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)

    left = Text()
    left.append("GLOSSARY", style=f"bold {_ACCENT}")
    if project_name:
        left.append("  ")
        left.append(project_name, style="bold")

    grid.add_row(left, Text(right, style="dim"))
    return grid


def _build_header(
    project_name: str, *, total: int, requested: int, related: int
) -> RenderableType:
    term_word = "term" if total == 1 else "terms"
    counts = f"{total} {term_word} · {requested} requested · {related} related"
    return _header_grid(project_name, counts)


def _build_node_blocks(
    node: GlossaryClosureNode, *, printed_indices: set[int]
) -> list[RenderableType]:
    indent = min(node.depth, _MAX_INDENT_DEPTH) * _INDENT_STEP

    title = Text()
    marker = "●" if node.origin == "requested" else "○"
    title.append(f"{marker} ", style=_ACCENT)
    title.append(node.entry.term, style="bold")

    if node.origin == "requested":
        tag, tag_style = "REQUESTED", "bold"
    else:
        tag, tag_style = f"RELATED · depth {node.depth}", "dim"

    header_row = Table.grid(expand=True, padding=(0, 0, 0, 2))
    header_row.add_column(ratio=1, overflow="fold")
    header_row.add_column(justify="right", no_wrap=True)
    header_row.add_row(title, Text(tag, style=tag_style))

    lines: list[RenderableType] = []

    if node.referrer is not None:
        provenance = Text()
        provenance.append("↳ mentioned as ", style="dim")
        provenance.append(f'"{node.referrer.matched_text}"', style=f"italic {_ACCENT}")
        provenance.append(" in ", style="dim")
        provenance.append(node.referrer.term, style="dim")
        lines.append(provenance)

    if node.also_referenced_by:
        lines.append(
            Text(
                "also mentioned by " + ", ".join(node.also_referenced_by),
                style="dim",
            )
        )

    if node.entry.display_aliases:
        lines.append(Text("aka " + " · ".join(node.entry.display_aliases), style="dim"))

    lines.append(_highlighted_definition(node, printed_indices=printed_indices))

    # Keep the tag table out of a Group with the body lines. Grouping them
    # right-pads every shorter body line to the header width.
    return [
        Padding(header_row, (0, 0, 0, indent)),
        *(Padding(line, (0, 0, 0, indent), expand=False) for line in lines),
    ]


def _highlighted_definition(
    node: GlossaryClosureNode, *, printed_indices: set[int]
) -> Text:
    definition = node.entry.definition.strip()
    text = Text()
    cursor = 0
    for span in node.spans:
        if span.entry_index == node.entry.index:
            continue
        if span.entry_index not in printed_indices:
            continue
        start = _char_offset_from_byte(definition, span.byte_start)
        end = _char_offset_from_byte(definition, span.byte_end)
        if start is None or end is None or start < cursor or end <= start:
            continue
        text.append(definition[cursor:start])
        text.append(definition[start:end], style=f"underline {_ACCENT}")
        cursor = end
    text.append(definition[cursor:])
    return text


def _build_footer(
    *, related: int, truncated: bool, depth_limit: int | None
) -> list[RenderableType]:
    lines: list[RenderableType] = []
    if related > 0 and depth_limit != 0:
        lines.append(Text("Use -d 0 to print only the requested terms.", style="dim"))
    if truncated:
        lines.append(
            Text(
                f"Truncated at depth {depth_limit}; raise -d or omit it to see more.",
                style="dim",
            )
        )
    return lines


def _char_offset_from_byte(text: str, byte_offset: int) -> int | None:
    try:
        return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))
    except UnicodeDecodeError:
        return None


# --- markdown -------------------------------------------------------------


def glossary_closure_markdown(closure: GlossaryClosure, *, project_name: str) -> str:
    """Render *closure* as plain Markdown suitable for pasting into a prompt."""
    pieces: list[str] = []
    if project_name:
        pieces.append(f"GLOSSARY: {project_name}\n")
    for node in closure.nodes:
        level = min(node.depth + 1, _MARKDOWN_MAX_HEADING_LEVEL)
        heading = "#" * level
        pieces.append(f"{heading} {node.entry.term}\n")
        pieces.append(f"*{_markdown_provenance(node)}*\n")
        if node.entry.display_aliases:
            pieces.append("aka " + ", ".join(node.entry.display_aliases) + "\n")
        pieces.append(node.entry.definition.strip() + "\n")
    return "\n".join(pieces) + "\n"


def _markdown_provenance(node: GlossaryClosureNode) -> str:
    if node.origin == "requested":
        return "Requested"
    parts = [f"Related · depth {node.depth}"]
    if node.referrer is not None:
        parts.append(
            f'mentioned as "{node.referrer.matched_text}" in {node.referrer.term}'
        )
    if node.also_referenced_by:
        parts.append("also mentioned by " + ", ".join(node.also_referenced_by))
    return " — ".join(parts)


# --- json -------------------------------------------------------------


def _glossary_closure_json_payload(
    closure: GlossaryClosure, *, project_name: str
) -> dict[str, object]:
    """Build the deterministic JSON payload for one glossary closure."""
    return {
        "project": project_name,
        "depth_limit": closure.depth_limit,
        "truncated": closure.truncated,
        "requested_references": closure.requested_references,
        "nodes": [_node_json(node) for node in closure.nodes],
    }


def _node_json(node: GlossaryClosureNode) -> dict[str, object]:
    return {
        "term": node.entry.term,
        "aliases": list(node.entry.display_aliases),
        "definition": node.entry.definition,
        "depth": node.depth,
        "origin": node.origin,
        "referrer": _referrer_json(node.referrer),
        "also_referenced_by": list(node.also_referenced_by),
    }


def _referrer_json(referrer: GlossaryReferrer | None) -> dict[str, str] | None:
    if referrer is None:
        return None
    return {"term": referrer.term, "matched_text": referrer.matched_text}


# --- catalog --------------------------------------------------------------


def render_glossary_catalog(
    closure: GlossaryClosure,
    *,
    project_name: str,
    output_format: GlossaryShowFormat,
    console: Console | None = None,
) -> None:
    """Print the full-catalog view of *closure* to stdout."""
    if output_format == "json":
        payload = _glossary_catalog_json_payload(closure, project_name=project_name)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if output_format == "markdown":
        sys.stdout.write(_glossary_catalog_markdown(closure, project_name=project_name))
        return

    target = console or Console()
    _print_rich_without_trailing_whitespace(
        target,
        _glossary_catalog_renderable(closure, project_name=project_name),
    )


def _glossary_catalog_renderable(
    closure: GlossaryClosure, *, project_name: str
) -> Group:
    """Build the dictionary-style Rich rendering for a full catalog."""
    if not closure.nodes:
        return Group(Text(_EMPTY_CATALOG.format(project=project_name)))

    n = len(closure.nodes)
    printed_indices = {node.entry.index for node in closure.nodes}
    term_word = "term" if n == 1 else "terms"
    blocks: list[RenderableType] = [
        _header_grid(project_name, f"{n} {term_word}"),
        Text(""),
    ]
    previous_key: str | None = None
    for node in closure.nodes:
        key = _catalog_group_key(node.entry.term)
        if key != previous_key:
            blocks.append(
                Rule(Text(key, style=f"bold {_ACCENT}"), align="left", style="dim")
            )
            blocks.append(Text(""))
            previous_key = key
        blocks.extend(
            _build_catalog_entry_blocks(node, printed_indices=printed_indices)
        )
        blocks.append(Text(""))
    blocks.append(Text(_AUDIT_HINT, style="dim"))
    return Group(*blocks)


def _catalog_group_key(term: str) -> str:
    first = term[:1].upper()
    return first if first.isalpha() else "#"


def _build_catalog_entry_blocks(
    node: GlossaryClosureNode, *, printed_indices: set[int]
) -> list[RenderableType]:
    title = Text()
    title.append("● ", style=_ACCENT)
    title.append(node.entry.term, style="bold")

    lines: list[RenderableType] = [title]
    if node.entry.display_aliases:
        lines.append(Text("aka " + " · ".join(node.entry.display_aliases), style="dim"))
    lines.append(_highlighted_definition(node, printed_indices=printed_indices))
    if node.also_referenced_by:
        lines.append(
            Text(
                "referenced by " + ", ".join(node.also_referenced_by),
                style="dim",
            )
        )
    return lines


def _glossary_catalog_markdown(closure: GlossaryClosure, *, project_name: str) -> str:
    """Render the full catalog as plain Markdown."""
    pieces: list[str] = []
    if project_name:
        pieces.append(f"GLOSSARY: {project_name}\n")
    for node in closure.nodes:
        pieces.append(f"# {node.entry.term}\n")
        if node.entry.display_aliases:
            pieces.append("aka " + ", ".join(node.entry.display_aliases) + "\n")
        pieces.append(node.entry.definition.strip() + "\n")
        if node.also_referenced_by:
            pieces.append("referenced by " + ", ".join(node.also_referenced_by) + "\n")
    return "\n".join(pieces) + "\n"


def _glossary_catalog_json_payload(
    closure: GlossaryClosure, *, project_name: str
) -> dict[str, object]:
    terms_by_index = {node.entry.index: node.entry.term for node in closure.nodes}
    return {
        "project": project_name,
        "count": len(closure.nodes),
        "terms": [_catalog_term_json(node, terms_by_index) for node in closure.nodes],
    }


def _catalog_term_json(
    node: GlossaryClosureNode, terms_by_index: Mapping[int, str]
) -> dict[str, object]:
    return {
        "term": node.entry.term,
        "aliases": list(node.entry.display_aliases),
        "definition": node.entry.definition,
        "reference_terms": list(_outbound_reference_terms(node, terms_by_index)),
        "referenced_by": list(node.also_referenced_by),
        "source": node.entry.source,
    }


def _outbound_reference_terms(
    node: GlossaryClosureNode, terms_by_index: Mapping[int, str]
) -> tuple[str, ...]:
    seen: set[int] = set()
    terms: list[str] = []
    for span in node.spans:
        if span.entry_index == node.entry.index or span.entry_index in seen:
            continue
        term = terms_by_index.get(span.entry_index)
        if term is None:
            continue
        seen.add(span.entry_index)
        terms.append(term)
    return tuple(terms)


__all__ = [
    "GlossaryShowFormat",
    "glossary_closure_markdown",
    "render_glossary_catalog",
    "render_glossary_closure",
]
