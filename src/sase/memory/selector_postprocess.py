"""Post-processing helpers for resolved memory selector batches."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, cast

from sase.memory.link_resolve import MemoryLinkTarget
from sase.memory.render import ResolvedMemoryNote


@dataclass(frozen=True, slots=True)
class MemorySelectorBatchUnit:
    """One top-level unit in the order a selector batch should print."""

    kind: Literal["note", "web"]
    key: str


class _WebLike(Protocol):
    @property
    def slug(self) -> str: ...


class _StrandLike(Protocol):
    @property
    def slug(self) -> str: ...


class _NodeLike(Protocol):
    @property
    def strand(self) -> _StrandLike: ...


class _SectionLike(Protocol):
    @property
    def web(self) -> _WebLike: ...

    @property
    def nodes(self) -> tuple[_NodeLike, ...]: ...

    @property
    def resolved_links(self) -> tuple[MemoryLinkTarget, ...]: ...


def suppress_rendered_targets[SectionT: _SectionLike](
    notes: tuple[ResolvedMemoryNote, ...],
    sections: tuple[SectionT, ...],
    *,
    link_target_key: Callable[[MemoryLinkTarget], str],
) -> tuple[tuple[ResolvedMemoryNote, ...], tuple[SectionT, ...]]:
    """Hide reference/child listings whose target body appears in this batch."""
    rendered_keys = _rendered_link_keys(
        notes, sections, link_target_key=link_target_key
    )
    rendered_note_paths = _rendered_note_paths(notes)

    filtered_notes = tuple(
        replace(
            note,
            suppress_child_paths=rendered_note_paths
            - frozenset({note.content.path.note.relative_path}),
            resolved_links=_filter_rendered_links(
                note.resolved_links,
                rendered_keys,
                link_target_key=link_target_key,
            ),
        )
        for note in notes
    )
    filtered_sections = tuple(
        cast(
            SectionT,
            replace(
                cast(Any, section),
                resolved_links=_filter_rendered_links(
                    section.resolved_links,
                    rendered_keys,
                    link_target_key=link_target_key,
                ),
            ),
        )
        for section in sections
    )
    return filtered_notes, filtered_sections


def select_memory_selector_render_units(
    candidates: Sequence[MemorySelectorBatchUnit],
    notes: tuple[ResolvedMemoryNote, ...],
    sections: tuple[_SectionLike, ...],
) -> tuple[MemorySelectorBatchUnit, ...]:
    """Return top-level render units in first requested selector order."""
    note_keys = {note.content.path.canonical_path for note in notes}
    web_keys = {section.web.slug for section in sections}
    seen: set[tuple[str, str]] = set()
    units: list[MemorySelectorBatchUnit] = []

    def add(unit: MemorySelectorBatchUnit) -> None:
        marker = (unit.kind, unit.key)
        if marker in seen:
            return
        seen.add(marker)
        units.append(unit)

    for unit in candidates:
        if unit.kind == "note" and unit.key in note_keys:
            add(unit)
        elif unit.kind == "web" and unit.key in web_keys:
            add(unit)

    for note in notes:
        add(MemorySelectorBatchUnit("note", note.content.path.canonical_path))
    for section in sections:
        add(MemorySelectorBatchUnit("web", section.web.slug))
    return tuple(units)


def _iter_note_tree(view: ResolvedMemoryNote) -> tuple[ResolvedMemoryNote, ...]:
    """Return *view* and every inline note descendant in render order."""
    notes: list[ResolvedMemoryNote] = [view]
    for inline_note in view.inline_notes:
        notes.extend(_iter_note_tree(inline_note))
    return tuple(notes)


def _rendered_note_paths(notes: tuple[ResolvedMemoryNote, ...]) -> frozenset[str]:
    paths: set[str] = set()
    for note in notes:
        for item in _iter_note_tree(note):
            paths.add(item.content.path.note.relative_path)
    return frozenset(paths)


def _rendered_link_keys(
    notes: tuple[ResolvedMemoryNote, ...],
    sections: tuple[_SectionLike, ...],
    *,
    link_target_key: Callable[[MemoryLinkTarget], str],
) -> frozenset[str]:
    keys: set[str] = set()
    for note in notes:
        for item in _iter_note_tree(note):
            keys.add(f"note:{item.content.path.canonical_path}")
    for section in sections:
        for node in section.nodes:
            keys.add(f"strand:{section.web.slug}:{node.strand.slug}")
    return frozenset(keys)


def _filter_rendered_links(
    links: tuple[MemoryLinkTarget, ...],
    rendered_keys: frozenset[str],
    *,
    link_target_key: Callable[[MemoryLinkTarget], str],
) -> tuple[MemoryLinkTarget, ...]:
    return tuple(link for link in links if link_target_key(link) not in rendered_keys)


__all__ = [
    "MemorySelectorBatchUnit",
    "select_memory_selector_render_units",
    "suppress_rendered_targets",
]
