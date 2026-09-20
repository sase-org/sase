"""Batch coordination and compatibility exports for ``memory read``/``show``.

Flat-note handling is implemented in :mod:`sase.memory.selector_notes`; web
and strand closure handling lives in :mod:`sase.memory.selector_web`.
"""

from __future__ import annotations

from pathlib import Path

from sase.main.init_memory.config import project_memory_name
from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.notes import MemoryNote, discover_memory_notes
from sase.memory.selector_models import (
    MemorySelectorKind,
    MemoryWebReadNode,
    MemoryWebReadSection,
    ResolvedMemorySelectorBatch,
    MemorySelectorError,
    NoteInlineContext,
    NoteSelector,
    StrandSelector,
    WebSelector,
    classify_selector,
    link_target_key,
)
from sase.memory.selector_notes import (
    note_selector_canonical_path,
    note_selector_keys,
    note_tree_keys,
    requested_note_keys,
    resolve_note_selector,
    validated_note_keys,
)
from sase.memory.selector_postprocess import (
    MemorySelectorBatchUnit,
    select_memory_selector_render_units,
    suppress_rendered_targets,
)
from sase.memory.selector_web import apply_note_strand_roots, resolve_web_sections
from sase.memory.web import ScopedMemoryWeb, discover_scoped_memory_webs


def resolve_memory_selector_batch(
    selectors: list[str],
    *,
    depth: int | None = None,
    project_ref: str | None = None,
    project_root: Path | None = None,
    home_root: Path | None = None,
) -> ResolvedMemorySelectorBatch:
    """Resolve every selector before emitting output or writing an audit event."""
    if not selectors:
        raise MemorySelectorError("at least one memory selector is required")
    resolved_home_root = home_root if home_root is not None else Path.home()
    try:
        cli_project = resolve_memory_cli_project(project_ref)
    except MemoryCliProjectError as exc:
        raise MemorySelectorError(str(exc)) from exc
    if cli_project is not None:
        resolved_project_root, project_name = (
            cli_project.project_root,
            cli_project.project_name,
        )
    else:
        resolved_project_root = project_root if project_root is not None else Path.cwd()
        project_name = project_memory_name(resolved_project_root)
    classified = [classify_selector(raw) for raw in selectors]
    has_note = any(isinstance(item, NoteSelector) for item in classified)
    has_web = any(isinstance(item, WebSelector) for item in classified)
    has_strand = any(isinstance(item, StrandSelector) for item in classified)
    link_notes, scoped_webs = _discover_link_universe(
        resolved_project_root, resolved_home_root
    )

    note_items = [item for item in classified if isinstance(item, NoteSelector)]
    requested_keys = requested_note_keys(
        note_items, project_root=resolved_project_root, home_root=resolved_home_root
    )
    inline_context = NoteInlineContext(pending_strand_roots=[])
    root_keys: set[str] = set()
    rendered_keys: set[str] = set()
    resolved_notes = []
    for item in note_items:
        item_keys = note_selector_keys(
            item, project_root=resolved_project_root, home_root=resolved_home_root
        )
        if item_keys & root_keys:
            continue
        note = resolve_note_selector(
            item,
            project_root=resolved_project_root,
            home_root=resolved_home_root,
            project_name=project_name,
            notes=link_notes,
            scoped_webs=scoped_webs,
            depth=depth,
            seen_note_paths=frozenset(requested_keys | rendered_keys),
            note_inline_context=inline_context,
        )
        resolved_notes.append(note)
        root_keys.update(item_keys)
        rendered_keys.update(note_tree_keys(note))
    notes = tuple(resolved_notes)

    web_sections, extra_notes = resolve_web_sections(
        classified,
        project_root=resolved_project_root,
        home_root=resolved_home_root,
        project_name=project_name,
        depth=depth,
        notes=link_notes,
        scoped_webs=scoped_webs,
        note_inline_context=inline_context,
        rendered_note_keys=frozenset(rendered_keys),
    )
    known_note_paths = {
        key
        for note in notes
        for key in validated_note_keys(
            note.content.path.canonical_path, note.content.path.note
        )
    }
    notes += tuple(
        note
        for note in extra_notes
        if not (
            validated_note_keys(
                note.content.path.canonical_path, note.content.path.note
            )
            & known_note_paths
        )
    )
    web_sections = apply_note_strand_roots(
        web_sections, inline_context.pending_strand_roots, scoped_webs=scoped_webs
    )
    notes, web_sections = suppress_rendered_targets(
        notes, web_sections, link_target_key=link_target_key
    )
    return ResolvedMemorySelectorBatch(
        project_name=project_name,
        notes=notes,
        web_sections=web_sections,
        selectors=tuple(selectors),
        depth=depth,
        has_note_selector=has_note,
        has_web_selector=has_web,
        has_strand_selector=has_strand,
        render_units=select_memory_selector_render_units(
            _render_unit_candidates(
                classified,
                project_root=resolved_project_root,
                home_root=resolved_home_root,
            ),
            notes,
            web_sections,
        ),
    )


def _discover_link_universe(
    project_root: Path,
    home_root: Path,
) -> tuple[tuple[MemoryNote, ...], tuple[ScopedMemoryWeb, ...]]:
    """Return project-over-home notes and webs used to resolve authored links."""
    project_notes = discover_memory_notes(project_root)
    home_notes = (
        ()
        if home_root.resolve(strict=False) == project_root.resolve(strict=False)
        else discover_memory_notes(home_root)
    )
    by_path: dict[str, MemoryNote] = {}
    for note in (*project_notes, *home_notes):
        by_path.setdefault(note.relative_path, note)
    return tuple(by_path.values()), discover_scoped_memory_webs(project_root, home_root)


def _render_unit_candidates(
    classified: list[NoteSelector | WebSelector | StrandSelector],
    *,
    project_root: Path,
    home_root: Path,
) -> tuple[MemorySelectorBatchUnit, ...]:
    return tuple(
        MemorySelectorBatchUnit(
            "note",
            note_selector_canonical_path(
                item, project_root=project_root, home_root=home_root
            ),
        )
        if isinstance(item, NoteSelector)
        else MemorySelectorBatchUnit("web", item.web_slug)
        for item in classified
    )


__all__ = [
    "MemorySelectorKind",
    "MemorySelectorBatchUnit",
    "MemoryWebReadNode",
    "MemoryWebReadSection",
    "ResolvedMemorySelectorBatch",
    "resolve_memory_selector_batch",
]
