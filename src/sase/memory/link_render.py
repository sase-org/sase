"""Linked References presentation for ``sase memory show``/``read``.

Markdown, rich, and JSON share one partition of a unit's ``resolved_links``:
resolved targets become numbered listings, unresolved targets trail as a
single ``Unresolved:`` line, and a unit with no reference links emits nothing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

from rich.console import Group, RenderableType
from rich.text import Text

from sase.cli_show_palette import PATH_COLOR, SECTION_COLOR
from sase.markdown_width import markdown_print_width
from sase.markdown_wrap import wrap_markdown
from sase.memory.link_resolve import (
    MemoryLinkTarget,
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    MemoryWebDescriptorLinkTarget,
    UnresolvedMemoryLinkTarget,
)
from sase.memory.web.frontmatter import slug_to_keyword

_MemoryLinkKind = Literal["inline", "reference"]

_ACCENT = SECTION_COLOR
_ALWAYS_LOADED_MARKER = "always-loaded core memory — already in your context"
_LINKED_REFERENCES_INTRO = (
    "The below memory files are linked from this one. Read one with your "
    "`/sase_memory_read`\n"
    "skill; do not open the file directly."
)


@dataclass(frozen=True, slots=True)
class _LinkedReference:
    """One resolved target as the Linked References listing presents it."""

    selector: str
    label: str
    summary: str
    always_loaded: bool


def append_memory_sections(body: str, *sections: str) -> str:
    """Join *body* to trailing Markdown sections with a blank line between each."""

    present = [section for section in sections if section]
    if not present:
        return body
    result = body
    if result and not result.endswith("\n"):
        result += "\n"
    for section in present:
        if result and not result.endswith("\n\n"):
            result += "\n"
        result += section
        if not result.endswith("\n"):
            result += "\n"
    return result


def _linked_reference_from_target(
    target: MemoryLinkTarget,
) -> _LinkedReference | None:
    """Return the listing row for a resolved *target*, or ``None`` if unresolved."""

    if isinstance(target, UnresolvedMemoryLinkTarget):
        return None
    if isinstance(target, MemoryStrandLinkTarget):
        return _LinkedReference(
            selector=target.address,
            label=target.strand.keyword,
            summary=_one_line(target.strand.summary),
            always_loaded=False,
        )
    if isinstance(target, MemoryNoteLinkTarget):
        stem = PurePosixPath(target.address).stem
        return _LinkedReference(
            selector=target.address,
            label=slug_to_keyword(stem),
            summary=_one_line(target.note.description),
            always_loaded=target.note.type == "core",
        )
    if isinstance(target, MemoryWebDescriptorLinkTarget):
        return _LinkedReference(
            selector=target.address,
            label=slug_to_keyword(target.address),
            summary=_one_line(target.web.description),
            always_loaded=True,
        )
    return None


def linked_references_markdown(targets: Sequence[MemoryLinkTarget]) -> str:
    """Return a ``## Linked References`` section, or ``""`` when *targets* is empty."""

    entries, unresolved = _partition_targets(targets)
    if not entries and not unresolved:
        return ""

    lines: list[str] = ["## Linked References", ""]
    if entries:
        lines.append(_LINKED_REFERENCES_INTRO)
        lines.append("")
        for index, entry in enumerate(entries, start=1):
            if index > 1:
                lines.append("")
            lines.append(f"### {index}. `{entry.selector}`")
            lines.append("")
            body = _entry_markdown_body(entry)
            if body:
                lines.append(body)
    if unresolved:
        if entries:
            lines.append("")
        tokens = ", ".join(f"`{raw}`" for raw in unresolved)
        lines.append(f"Unresolved: {tokens}")
    return "\n".join(lines) + "\n"


def linked_references_renderable(
    targets: Sequence[MemoryLinkTarget],
) -> RenderableType | None:
    """Return a rich Linked References block, or ``None`` when *targets* is empty."""

    entries, unresolved = _partition_targets(targets)
    if not entries and not unresolved:
        return None

    lines: list[RenderableType] = [Text("Linked References", style=f"bold {_ACCENT}")]
    for index, entry in enumerate(entries, start=1):
        heading = Text()
        heading.append(f"{index}. ", style="dim")
        heading.append(entry.selector, style=PATH_COLOR)
        if entry.always_loaded:
            heading.append(f" ({_ALWAYS_LOADED_MARKER})", style="dim")
        lines.append(heading)
        detail = _entry_rich_detail(entry)
        if detail is not None:
            lines.append(detail)
    if unresolved:
        unresolved_line = Text("Unresolved: ", style="dim")
        unresolved_line.append(", ".join(unresolved), style="dim")
        lines.append(unresolved_line)
    return Group(*lines)


def linked_references_json(
    targets: Sequence[MemoryLinkTarget],
) -> list[dict[str, object]]:
    """Return the ``linked_references`` payload for a note or web-section unit."""

    entries, _unresolved = _partition_targets(targets)
    return [
        {
            "address": entry.selector,
            "always_loaded": entry.always_loaded,
            "label": entry.label,
            "summary": entry.summary,
        }
        for entry in entries
    ]


def memory_links_json(
    items: Sequence[tuple[MemoryLinkTarget, _MemoryLinkKind]],
) -> list[dict[str, object]]:
    """Return the per-unit ``links`` payload for a note or strand node."""

    payload: list[dict[str, object]] = []
    for target, kind in items:
        entry = _linked_reference_from_target(target)
        payload.append(
            {
                "address": None if entry is None else entry.selector,
                "kind": kind,
                "label": None if entry is None else entry.label,
                "resolved": entry is not None,
                "summary": None if entry is None else entry.summary,
                "target": target.raw,
            }
        )
    return payload


def _partition_targets(
    targets: Sequence[MemoryLinkTarget],
) -> tuple[tuple[_LinkedReference, ...], tuple[str, ...]]:
    entries: list[_LinkedReference] = []
    unresolved: list[str] = []
    seen_unresolved: set[str] = set()
    for target in targets:
        if isinstance(target, UnresolvedMemoryLinkTarget):
            if target.raw in seen_unresolved:
                continue
            seen_unresolved.add(target.raw)
            unresolved.append(target.raw)
            continue
        entry = _linked_reference_from_target(target)
        if entry is not None:
            entries.append(entry)
    return tuple(entries), tuple(unresolved)


def _entry_markdown_body(entry: _LinkedReference) -> str:
    line = _entry_plain_line(entry)
    if not line:
        return ""
    return wrap_markdown(line, width=markdown_print_width())


def _entry_rich_detail(entry: _LinkedReference) -> Text | None:
    if not entry.label and not entry.summary:
        return None
    detail = Text()
    if entry.label:
        detail.append(entry.label, style="bold")
        if entry.summary:
            detail.append(" — ", style="dim")
            detail.append(entry.summary, style="dim")
    else:
        detail.append(entry.summary, style="dim")
    return detail


def _entry_plain_line(entry: _LinkedReference) -> str:
    if entry.label and entry.summary:
        line = f"**{entry.label}** — {entry.summary}"
    elif entry.label:
        line = f"**{entry.label}**"
    else:
        line = entry.summary
    if entry.always_loaded:
        marker = f"({_ALWAYS_LOADED_MARKER})"
        return f"{line} {marker}" if line else marker
    return line


def _one_line(value: str | None) -> str:
    return " ".join((value or "").split())


__all__ = [
    "append_memory_sections",
    "linked_references_json",
    "linked_references_markdown",
    "linked_references_renderable",
    "memory_links_json",
]
