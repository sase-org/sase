"""Rendering for a resolved ``memory read``/``show`` selector batch.

A batch of exactly one note selector renders byte-identically to today's
single-note :func:`~sase.memory.render.render_memory_note`, so every
existing note-only consumer sees no change. Any batch that includes a web or
strand selector — or more than one note — renders through the combined
batch shapes here instead.
"""

from __future__ import annotations

import json
import sys
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.memory.render import (
    MemoryShowFormat,
    ResolvedMemoryNote,
    memory_note_markdown,
    render_memory_note,
)
from sase.memory.selector import (
    MemoryWebReadNode,
    MemoryWebReadSection,
    ResolvedMemorySelectorBatch,
)

_ACCENT = SECTION_COLOR


def render_memory_selector_batch(
    batch: ResolvedMemorySelectorBatch,
    *,
    output_format: MemoryShowFormat,
    console: Console | None = None,
) -> None:
    """Print *batch* to stdout in the requested format."""
    if batch.is_single_note:
        render_memory_note(batch.notes[0], output_format=output_format, console=console)
        return

    if output_format == "json":
        payload = _batch_json_payload(batch)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if output_format == "markdown":
        sys.stdout.write(memory_selector_batch_markdown(batch))
        return

    target = console or Console()
    for note in batch.notes:
        render_memory_note(note, output_format="rich", console=target)
    for section in batch.web_sections:
        target.print(_web_section_renderable(section))


# --- json -------------------------------------------------------------


def _batch_json_payload(batch: ResolvedMemorySelectorBatch) -> dict[str, object]:
    return {
        "project": batch.project_name,
        "selectors": list(batch.selectors),
        "depth": batch.depth,
        "notes": [_note_json(note) for note in batch.notes],
        "webs": [_web_section_json(section) for section in batch.web_sections],
    }


def _note_json(note: ResolvedMemoryNote) -> dict[str, object]:
    memory_note = note.content.path.note
    return {
        "path": memory_note.relative_path,
        "canonical_path": note.content.path.canonical_path,
        "type": memory_note.type,
        "description": memory_note.description,
        "body": note.content.body,
        "byte_count": note.content.byte_count,
        "origin": note.origin,
    }


def _web_section_json(section: MemoryWebReadSection) -> dict[str, object]:
    return {
        "web": section.web.slug,
        "strand_noun": section.web.strand_noun,
        "depth_limit": section.depth_limit,
        "truncated": section.truncated,
        "nodes": [_node_json(node) for node in section.nodes],
    }


def _node_json(node: MemoryWebReadNode) -> dict[str, object]:
    return {
        "slug": node.strand.slug,
        "keyword": node.strand.keyword,
        "aliases": list(node.strand.aliases),
        "summary": node.strand.summary,
        "body": node.strand.body,
        "origin": node.origin,
        "depth": node.depth,
        "scope": node.scope,
        "referrer": None if node.referrer is None else list(node.referrer),
        "also_referenced_by": list(node.also_referenced_by),
    }


# --- markdown -----------------------------------------------------------


def memory_selector_batch_markdown(batch: ResolvedMemorySelectorBatch) -> str:
    """Return the Markdown ``sase memory show`` prints for a selector batch."""
    if batch.is_single_note:
        return memory_note_markdown(batch.notes[0])
    return _batch_markdown(batch)


_MARKDOWN_SECTION_RULE = "-" * 10


def _batch_markdown(batch: ResolvedMemorySelectorBatch) -> str:
    pieces: list[str] = []
    for note in batch.notes:
        pieces.append(_note_section_markdown(note))
    for section in batch.web_sections:
        pieces.append(_web_section_markdown(section))
    return "\n".join(piece.rstrip("\n") for piece in pieces) + "\n"


def _markdown_section_header(kind: Literal["FILE", "WEB"], name: str) -> str:
    """Return a combined-batch Markdown section header.

    Combined Markdown is the only path that labels sections. Each header
    starts on a new line after one blank line, including the first header
    in the command output.
    """
    return f"\n{_MARKDOWN_SECTION_RULE} MEMORY {kind}: {name}\n"


def _note_section_markdown(note: ResolvedMemoryNote) -> str:
    header = _markdown_section_header("FILE", note.content.path.canonical_path)
    return "\n".join([header, memory_note_markdown(note)])


def _web_section_markdown(section: MemoryWebReadSection) -> str:
    pieces = [_markdown_section_header("WEB", section.web.slug)]
    for node in section.nodes:
        level = min(node.depth + 1, 6)
        pieces.append(f"{'#' * level} {node.strand.keyword}\n")
        pieces.append(f"*{_provenance_label(node)}*\n")
        if node.strand.aliases:
            pieces.append("aka " + ", ".join(node.strand.aliases) + "\n")
        pieces.append(node.strand.body.strip() + "\n")
    return "\n".join(pieces)


def _provenance_reference(node: MemoryWebReadNode) -> str | None:
    if node.referrer is None:
        return None
    term, matched_text, kind = node.referrer
    if kind == "link":
        return f"linked from {term}"
    return f'mentioned as "{matched_text}" in {term}'


def _provenance_label(node: MemoryWebReadNode) -> str:
    if node.origin == "requested":
        return f"Requested · {node.scope}"
    parts = [f"Related · depth {node.depth} · {node.scope}"]
    reference = _provenance_reference(node)
    if reference is not None:
        parts.append(reference)
    if node.also_referenced_by:
        parts.append("also mentioned by " + ", ".join(node.also_referenced_by))
    return " — ".join(parts)


# --- rich -----------------------------------------------------------------


def _web_section_renderable(section: MemoryWebReadSection) -> Group:
    requested = sum(1 for node in section.nodes if node.origin == "requested")
    related = len(section.nodes) - requested
    blocks: list[RenderableType] = [
        _web_header(section, requested=requested, related=related)
    ]
    blocks.append(Text(""))
    for node in section.nodes:
        blocks.extend(_node_blocks(node))
        blocks.append(Text(""))
    if section.truncated:
        blocks.append(
            Text(
                f"Truncated at depth {section.depth_limit}; raise -d or omit it to see more.",
                style="dim",
            )
        )
    return Group(*blocks)


def _web_header(
    section: MemoryWebReadSection, *, requested: int, related: int
) -> RenderableType:
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)

    left = Text()
    left.append("MEMORY WEB", style=f"bold {_ACCENT}")
    left.append("  ")
    left.append(section.web.slug, style=f"bold {PATH_COLOR}")

    strand_word = "strand" if requested + related == 1 else "strands"
    grid.add_row(
        left,
        Text(
            f"{requested + related} {strand_word} · {requested} requested · {related} related",
            style="dim",
        ),
    )
    return grid


def _node_blocks(node: MemoryWebReadNode) -> list[RenderableType]:
    indent = min(node.depth, 3) * 2

    title = Text()
    marker = "●" if node.origin == "requested" else "○"
    title.append(f"{marker} ", style=_ACCENT)
    title.append(node.strand.keyword, style="bold")

    tag: Literal["REQUESTED"] | str
    tag = "REQUESTED" if node.origin == "requested" else f"RELATED · depth {node.depth}"
    header_row = Table.grid(expand=True, padding=(0, 0, 0, 2))
    header_row.add_column(ratio=1, overflow="fold")
    header_row.add_column(justify="right", no_wrap=True)
    header_row.add_row(
        title, Text(tag, style="bold" if node.origin == "requested" else "dim")
    )

    lines: list[RenderableType] = []
    if node.referrer is not None:
        term, matched_text, kind = node.referrer
        provenance = Text()
        if kind == "link":
            provenance.append("↳ linked from ", style="dim")
            provenance.append(term, style=f"italic {_ACCENT}")
        else:
            provenance.append("↳ mentioned as ", style="dim")
            provenance.append(f'"{matched_text}"', style=f"italic {_ACCENT}")
            provenance.append(" in ", style="dim")
            provenance.append(term, style="dim")
        lines.append(provenance)
    if node.also_referenced_by:
        lines.append(
            Text("also mentioned by " + ", ".join(node.also_referenced_by), style="dim")
        )
    if node.strand.aliases:
        lines.append(Text("aka " + " · ".join(node.strand.aliases), style="dim"))
    lines.append(Text(f"scope: {node.scope}", style="dim"))
    lines.append(Text(node.strand.body.strip()))

    return [
        Padding(header_row, (0, 0, 0, indent)),
        *(Padding(line, (0, 0, 0, indent), expand=False) for line in lines),
    ]


__all__ = ["memory_selector_batch_markdown", "render_memory_selector_batch"]
