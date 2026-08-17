"""Shared rendering for ``sase glossary show``/``read`` output.

``show`` and ``read`` resolve a :class:`~sase.glossary.resolution.GlossaryClosure`
through identical code and must print identical output for identical
arguments, so both route through :func:`render_glossary_closure`.
"""

from __future__ import annotations

import json
import sys
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import SECTION_COLOR
from sase.glossary.resolution import GlossaryClosure, GlossaryClosureNode

GlossaryShowFormat = Literal["json", "markdown", "rich"]

_INDENT_STEP = 2
_MAX_INDENT_DEPTH = 3
_ACCENT = SECTION_COLOR
_MARKDOWN_MAX_HEADING_LEVEL = 6


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
        sys.stdout.write(_glossary_closure_markdown(closure, project_name=project_name))
        return

    target = console or Console()
    target.print(_glossary_closure_renderable(closure, project_name=project_name))


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
        Text(""),
    ]
    for node in closure.nodes:
        blocks.append(_build_node_block(node, printed_indices=printed_indices))
        blocks.append(Text(""))
    blocks.append(
        _build_footer(
            related=related,
            truncated=closure.truncated,
            depth_limit=closure.depth_limit,
        )
    )
    return Group(*blocks)


def _build_header(
    project_name: str, *, total: int, requested: int, related: int
) -> RenderableType:
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)

    left = Text()
    left.append("GLOSSARY", style=f"bold {_ACCENT}")
    if project_name:
        left.append("  ")
        left.append(project_name, style="bold")

    term_word = "term" if total == 1 else "terms"
    counts = f"{total} {term_word} · {requested} requested · {related} related"
    grid.add_row(left, Text(counts, style="dim"))
    return grid


def _build_node_block(
    node: GlossaryClosureNode, *, printed_indices: set[int]
) -> RenderableType:
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

    lines: list[RenderableType] = [header_row]

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

    return Padding(Group(*lines), (0, 0, 0, indent))


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
) -> RenderableType:
    lines: list[RenderableType] = []
    if related > 0:
        lines.append(
            Text(
                "Related terms were printed because the definitions above "
                "mention them.",
                style="dim",
            )
        )
    lines.append(Text("Use -d 0 to print only the requested terms.", style="dim"))
    if truncated:
        lines.append(
            Text(
                f"Truncated at depth {depth_limit}; raise -d or omit it to see more.",
                style="dim",
            )
        )
    return Group(*lines)


def _char_offset_from_byte(text: str, byte_offset: int) -> int | None:
    try:
        return len(text.encode("utf-8")[:byte_offset].decode("utf-8"))
    except UnicodeDecodeError:
        return None


# --- markdown -------------------------------------------------------------


def _glossary_closure_markdown(closure: GlossaryClosure, *, project_name: str) -> str:
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
        "nodes": [_node_json(node) for node in closure.nodes],
    }


def _node_json(node: GlossaryClosureNode) -> dict[str, object]:
    return {
        "term": node.entry.term,
        "aliases": list(node.entry.display_aliases),
        "definition": node.entry.definition,
        "depth": node.depth,
        "origin": node.origin,
        "referrer": None
        if node.referrer is None
        else {"term": node.referrer.term, "matched_text": node.referrer.matched_text},
        "also_referenced_by": list(node.also_referenced_by),
    }


__all__ = [
    "GlossaryShowFormat",
    "render_glossary_closure",
]
