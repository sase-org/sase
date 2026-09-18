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
from sase.memory.link_render import (
    append_memory_sections,
    linked_references_json,
    linked_references_markdown,
    linked_references_renderable,
    memory_links_json,
)
from sase.memory.link_resolve import MemoryLinkTarget, MemoryNoteLinkTarget
from sase.memory.notes import MemoryNote, render_children_section
from sase.memory.read_log import MemoryReadContent

MemoryShowFormat = Literal["json", "markdown", "rich"]

_ACCENT = SECTION_COLOR


@dataclass(frozen=True, slots=True)
class ResolvedMemoryNoteLink:
    """One authored link from a flat note, classified for output."""

    target: MemoryLinkTarget
    kind: Literal["inline", "reference"]


@dataclass(frozen=True, slots=True)
class ResolvedMemoryNote:
    """A validated reference memory note plus the context show/read print."""

    content: MemoryReadContent
    children: tuple[MemoryNote, ...]
    origin: Literal["home", "project"]
    project_name: str
    render_origin: Literal["requested", "related"] = "requested"
    suppress_child_paths: frozenset[str] = frozenset()
    resolved_links: tuple[MemoryLinkTarget, ...] = ()
    links: tuple[ResolvedMemoryNoteLink, ...] = ()
    inline_notes: tuple[ResolvedMemoryNote, ...] = ()


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


def _note_children(
    view: ResolvedMemoryNote, *, exclude_paths: frozenset[str] = frozenset()
) -> tuple[MemoryNote, ...]:
    """Return *view*'s children, filtered from the discovered notes."""
    parent_keys = {
        view.content.path.canonical_path,
        view.content.path.note.relative_path,
    }
    children = (
        note
        for note in view.children
        if note.type == "reference"
        and note.parent in parent_keys
        and note.relative_path not in exclude_paths
    )
    return tuple(sorted(children, key=lambda note: note.relative_path))


def memory_note_children(view: ResolvedMemoryNote) -> tuple[MemoryNote, ...]:
    """Return visible reference children for *view* after inline suppression."""
    return _note_children(view, exclude_paths=_suppressed_child_paths(view))


def _inline_note_reference_paths(view: ResolvedMemoryNote) -> frozenset[str]:
    """Return relative paths for every note rendered inline under *view*."""
    paths: set[str] = set()
    for note in view.inline_notes:
        paths.add(note.content.path.note.relative_path)
        paths.update(_inline_note_reference_paths(note))
    return frozenset(paths)


def _suppressed_child_paths(view: ResolvedMemoryNote) -> frozenset[str]:
    """Return child paths whose bodies already appear in the rendered output."""
    return (
        _inline_note_reference_paths(view)
        | _linked_note_reference_paths(view)
        | view.suppress_child_paths
    )


def _linked_note_reference_paths(view: ResolvedMemoryNote) -> frozenset[str]:
    """Return relative paths for note targets listed in Linked References."""
    return frozenset(
        target.note.relative_path
        for target in view.resolved_links
        if isinstance(target, MemoryNoteLinkTarget)
    )


def _memory_note_link_items(
    view: ResolvedMemoryNote,
) -> tuple[tuple[MemoryLinkTarget, Literal["inline", "reference"]], ...]:
    """Return per-note links, preserving old reference-only defaults."""
    if view.links:
        return tuple((link.target, link.kind) for link in view.links)
    return tuple((target, "reference") for target in view.resolved_links)


# --- markdown -----------------------------------------------------------


def _memory_note_markdown(view: ResolvedMemoryNote) -> str:
    """Render *view* as the plain Markdown ``sase memory read`` prints today."""
    body = _memory_note_body_markdown(view)
    children_section = render_children_section(
        view.children,
        view.content.path.note,
        exclude_paths=_suppressed_child_paths(view),
    )
    linked_section = linked_references_markdown(view.resolved_links)
    return append_memory_sections(body, children_section, linked_section)


def _memory_note_body_markdown(view: ResolvedMemoryNote) -> str:
    """Return a note body plus the bodies of any inline note closure."""
    return append_memory_sections(
        view.content.body,
        *(_inline_note_markdown(note) for note in view.inline_notes),
    )


def _inline_note_markdown(view: ResolvedMemoryNote) -> str:
    """Return an inline note body plus discoverable unread child rows."""
    children_section = render_children_section(
        view.children,
        view.content.path.note,
        exclude_paths=_suppressed_child_paths(view),
    )
    return append_memory_sections(_memory_note_body_markdown(view), children_section)


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
            "links": memory_links_json(_memory_note_link_items(view)),
            "inline_notes": [_inline_note_json(note) for note in view.inline_notes],
        },
        "children": [
            _child_json(child)
            for child in _note_children(
                view, exclude_paths=_suppressed_child_paths(view)
            )
        ],
        "linked_references": linked_references_json(view.resolved_links),
    }


def _inline_note_json(view: ResolvedMemoryNote) -> dict[str, object]:
    note = view.content.path.note
    return {
        "path": note.relative_path,
        "canonical_path": view.content.path.canonical_path,
        "description": note.description,
        "body": view.content.body,
        "links": memory_links_json(_memory_note_link_items(view)),
        "inline_notes": [_inline_note_json(child) for child in view.inline_notes],
        "children": [_child_json(child) for child in memory_note_children(view)],
        "linked_references": linked_references_json(view.resolved_links),
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
    for inline_note in view.inline_notes:
        blocks.append(Text(""))
        blocks.append(Markdown(_inline_note_markdown(inline_note)))

    children = _note_children(view, exclude_paths=_suppressed_child_paths(view))
    if children:
        blocks.append(Text(""))
        blocks.append(_build_children_block(children))
    linked_block = linked_references_renderable(view.resolved_links)
    if linked_block is not None:
        blocks.append(Text(""))
        blocks.append(linked_block)
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
    child_count = len(_note_children(view, exclude_paths=_suppressed_child_paths(view)))
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
    "ResolvedMemoryNoteLink",
    "memory_note_markdown",
    "render_memory_note",
]
