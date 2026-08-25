"""Shared rendering for ``sase memory show``/``read`` output.

``show`` and ``read`` resolve a :class:`ResolvedMemoryNote` through identical
code and must print identical output for identical arguments, so both route
through :func:`render_memory_note`.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Literal

from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.memory.notes import MemoryNote, render_children_section
from sase.memory.read_log import MemoryReadContent

MemoryShowFormat = Literal["json", "markdown", "rich"]

_ACCENT = SECTION_COLOR


@dataclass(frozen=True, slots=True)
class ResolvedMemoryNote:
    """A validated reference memory note plus the context show/read print."""

    content: MemoryReadContent
    children: tuple[MemoryNote, ...]
    origin: Literal["home", "project"]
    project_name: str


def render_memory_note(
    view: ResolvedMemoryNote,
    *,
    output_format: MemoryShowFormat,
    console: Console | None = None,
) -> None:
    """Print *view* to stdout in the requested format."""
    if output_format == "json":
        payload = _memory_note_json_payload(view)
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return

    if output_format == "markdown":
        sys.stdout.write(_memory_note_markdown(view))
        return

    target = console or Console()
    target.print(_memory_note_renderable(view))


# --- shared -----------------------------------------------------------


def _note_children(view: ResolvedMemoryNote) -> tuple[MemoryNote, ...]:
    """Return *view*'s children, filtered from the discovered notes."""
    parent_key = view.content.path.note.relative_path
    children = (
        note
        for note in view.children
        if note.type == "reference" and note.parent == parent_key
    )
    return tuple(sorted(children, key=lambda note: note.relative_path))


# --- markdown -----------------------------------------------------------


def _memory_note_markdown(view: ResolvedMemoryNote) -> str:
    """Render *view* as the plain Markdown ``sase memory read`` prints today."""
    children_section = render_children_section(view.children, view.content.path.note)
    if not children_section:
        return view.content.body

    body = view.content.body
    if body and not body.endswith("\n"):
        body += "\n"
    if body and not body.endswith("\n\n"):
        body += "\n"
    return body + children_section


def memory_note_markdown(view: ResolvedMemoryNote) -> str:
    """Return the Markdown ``sase memory show`` prints for one note view."""
    return _memory_note_markdown(view)


# --- json -----------------------------------------------------------------


def _memory_note_json_payload(view: ResolvedMemoryNote) -> dict[str, object]:
    note = view.content.path.note
    return {
        "project": view.project_name,
        "origin": view.origin,
        "note": {
            "path": note.relative_path,
            "canonical_path": view.content.path.canonical_path,
            "resolved_path": str(view.content.path.resolved_path),
            "type": note.type,
            "parent": note.parent,
            "description": note.description,
            "body": view.content.body,
            "byte_count": view.content.byte_count,
            "frontmatter_stripped": view.content.frontmatter_stripped,
        },
        "children": [_child_json(child) for child in _note_children(view)],
    }


def _child_json(child: MemoryNote) -> dict[str, str | None]:
    return {"path": child.relative_path, "description": child.description}


# --- rich -------------------------------------------------------------


def _memory_note_renderable(view: ResolvedMemoryNote) -> Group:
    note = view.content.path.note
    blocks: list[RenderableType] = [_build_header(view)]
    if note.description:
        blocks.append(Text(note.description, style="dim"))
    blocks.append(Text(""))
    blocks.append(Markdown(view.content.body))

    children = _note_children(view)
    if children:
        blocks.append(Text(""))
        blocks.append(_build_children_block(children))
    return Group(*blocks)


def _build_header(view: ResolvedMemoryNote) -> RenderableType:
    note = view.content.path.note
    grid = Table.grid(expand=True, padding=(0, 0, 0, 2))
    grid.add_column(ratio=1, overflow="fold")
    grid.add_column(justify="right", no_wrap=True)

    left = Text()
    left.append("MEMORY", style=f"bold {_ACCENT}")
    left.append("  ")
    left.append(note.relative_path, style=f"bold {PATH_COLOR}")

    parts = [view.origin, note.type or "reference"]
    child_count = len(_note_children(view))
    if child_count:
        word = "child" if child_count == 1 else "children"
        parts.append(f"{child_count} {word}")
    grid.add_row(left, Text(" · ".join(parts), style="dim"))
    return grid


def _build_children_block(children: tuple[MemoryNote, ...]) -> RenderableType:
    lines: list[RenderableType] = [Text("Children", style=f"bold {_ACCENT}")]
    for child in children:
        line = Text()
        line.append(child.relative_path, style=PATH_COLOR)
        if child.description:
            line.append(" — ", style="dim")
            line.append(child.description, style="dim")
        lines.append(line)
    return Group(*lines)


__all__ = [
    "MemoryShowFormat",
    "ResolvedMemoryNote",
    "memory_note_markdown",
    "render_memory_note",
]
