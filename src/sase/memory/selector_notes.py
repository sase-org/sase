"""Flat-note resolution helpers for memory selector batches."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from sase.memory.link_resolve import (
    MemoryLinkTarget,
    MemoryNoteLinkTarget,
    MemoryStrandLinkTarget,
    resolve_memory_link_target,
)
from sase.memory.links import scan_memory_links
from sase.memory.notes import MemoryNote, discover_memory_notes
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    LEGACY_MEMORY_RELATIVE_ROOT,
)
from sase.memory.read_log import (
    MemoryReadError,
    MemoryReadPathError,
    read_memory_content,
    validate_memory_read_path,
)
from sase.memory.render import ResolvedMemoryNote, ResolvedMemoryNoteLink
from sase.memory.selector_models import (
    _MemorySelectorError,
    _NoteInlineContext,
    _NoteSelector,
    _PendingNoteStrandRoot,
    _ResolvedNoteLinks,
    always_reference_target,
    link_target_key,
)
from sase.memory.web import ScopedMemoryWeb


def requested_note_keys(
    items: list[_NoteSelector], *, project_root: Path, home_root: Path
) -> frozenset[str]:
    """Return identity keys for top-level note selectors in the batch."""
    keys: set[str] = set()
    for item in items:
        keys.update(
            note_selector_keys(item, project_root=project_root, home_root=home_root)
        )
    return frozenset(keys)


def note_selector_keys(
    item: _NoteSelector, *, project_root: Path, home_root: Path
) -> frozenset[str]:
    """Return identity keys for one top-level note selector."""
    try:
        validated_path = validate_memory_read_path(
            item.path, project_root=project_root, home_root=home_root
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(note_selector_error(item, exc)) from exc
    return validated_note_keys(validated_path.canonical_path, validated_path.note)


def note_selector_canonical_path(
    item: _NoteSelector, *, project_root: Path, home_root: Path
) -> str:
    """Return the canonical path for one top-level note selector."""
    try:
        validated_path = validate_memory_read_path(
            item.path, project_root=project_root, home_root=home_root
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(note_selector_error(item, exc)) from exc
    return validated_path.canonical_path


def validated_note_keys(canonical_path: str, note: MemoryNote) -> frozenset[str]:
    """Return equivalent path keys that identify one flat memory note."""
    return frozenset({canonical_path, note.relative_path})


def note_target_keys(target: MemoryNoteLinkTarget) -> frozenset[str]:
    """Return equivalent path keys that identify a note link target."""
    return frozenset({target.address, target.note.relative_path})


def note_tree_keys(view: ResolvedMemoryNote) -> frozenset[str]:
    """Return identity keys for every note rendered by *view*."""
    keys: set[str] = set(
        validated_note_keys(view.content.path.canonical_path, view.content.path.note)
    )
    for inline_note in view.inline_notes:
        keys.update(note_tree_keys(inline_note))
    return frozenset(keys)


def resolve_note_selector(
    item: _NoteSelector,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
    seen_note_paths: frozenset[str] = frozenset(),
    note_inline_context: _NoteInlineContext | None = None,
) -> ResolvedMemoryNote:
    """Resolve a flat-note selector and any eligible inline linked notes."""
    try:
        validated_path = validate_memory_read_path(
            item.path, project_root=project_root, home_root=home_root
        )
    except MemoryReadPathError as exc:
        raise _MemorySelectorError(note_selector_error(item, exc)) from exc

    content = read_memory_content(validated_path)
    children = discover_memory_notes(content.path.content_root)
    resolved_home_root = home_root.expanduser().resolve(strict=False)
    origin: Literal["home", "project"] = (
        "home" if content.path.content_root == resolved_home_root else "project"
    )
    current_seen = set(seen_note_paths)
    current_seen.update(
        validated_note_keys(content.path.canonical_path, content.path.note)
    )
    resolved = resolve_note_links(
        content.body,
        source_note=content.path.note,
        notes=notes,
        scoped_webs=scoped_webs,
        depth=depth,
        project_root=project_root,
        home_root=home_root,
        project_name=project_name,
        seen_note_paths=frozenset(current_seen),
        note_inline_context=note_inline_context,
    )
    return ResolvedMemoryNote(
        content=content,
        children=children,
        origin=origin,
        project_name=project_name,
        resolved_links=resolved.references,
        links=resolved.links,
        inline_notes=resolved.inline_notes,
    )


def note_selector_error(item: _NoteSelector, exc: MemoryReadPathError) -> str:
    """Suggest a ``web:keyword`` selector for a nested-looking ``.md`` typo."""
    message = str(exc)
    if "flat" not in message:
        return message
    parts = Path(item.path).parts
    for prefix in (
        CANONICAL_MEMORY_RELATIVE_ROOT.parts,
        LEGACY_MEMORY_RELATIVE_ROOT.parts,
    ):
        if parts[: len(prefix)] == prefix:
            parts = parts[len(prefix) :]
            break
    if len(parts) == 2 and parts[1].endswith(".md"):
        return f"{message}; did you mean {parts[0]}:{parts[1][: -len('.md')]}?"
    return message


def resolve_note_links(
    body: str,
    *,
    source_note: MemoryNote,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
    project_root: Path,
    home_root: Path,
    project_name: str,
    seen_note_paths: frozenset[str],
    note_inline_context: _NoteInlineContext | None,
) -> _ResolvedNoteLinks:
    """Scan and resolve a flat note's authored links."""
    if source_note.link_reference == "none":
        return _ResolvedNoteLinks(links=(), inline_notes=(), references=())
    links: list[ResolvedMemoryNoteLink] = []
    inline_notes: list[ResolvedMemoryNote] = []
    references: list[MemoryLinkTarget] = []
    seen_references: set[str] = set()
    seen_rendered_notes = set(seen_note_paths)

    def add_reference(target: MemoryLinkTarget) -> None:
        key = link_target_key(target)
        if key not in seen_references:
            seen_references.add(key)
            references.append(target)

    def remove_reference(target: MemoryLinkTarget) -> None:
        key = link_target_key(target)
        if key in seen_references:
            seen_references.remove(key)
            references[:] = [
                item for item in references if link_target_key(item) != key
            ]

    for link in scan_memory_links(body):
        target = resolve_memory_link_target(
            link.target, notes=notes, scoped_webs=scoped_webs, source_note=source_note
        )
        if target is None:
            continue
        inline = depth != 0 and (link.inline or source_note.link_rendering == "inline")
        if inline and always_reference_target(target):
            inline = False
        kind: Literal["inline", "reference"] = "inline" if inline else "reference"
        links.append(ResolvedMemoryNoteLink(target=target, kind=kind))
        if isinstance(target, MemoryNoteLinkTarget):
            target_keys = note_target_keys(target)
            if target_keys & seen_rendered_notes:
                continue
            if inline:
                inline_note = resolve_extra_note(
                    target,
                    project_root=project_root,
                    home_root=home_root,
                    project_name=project_name,
                    notes=notes,
                    scoped_webs=scoped_webs,
                    depth=None if depth is None else depth - 1,
                    seen_note_paths=frozenset(seen_rendered_notes | set(target_keys)),
                    note_inline_context=note_inline_context,
                )
                if inline_note is not None:
                    inline_notes.append(inline_note)
                    seen_rendered_notes.update(note_tree_keys(inline_note))
                    remove_reference(target)
                    for reference in inline_note.resolved_links:
                        add_reference(reference)
                    continue
            add_reference(target)
        elif inline and isinstance(target, MemoryStrandLinkTarget):
            if note_inline_context is not None:
                note_inline_context.pending_strand_roots.append(
                    _PendingNoteStrandRoot(
                        source_note=source_note, target=target, link=link
                    )
                )
        else:
            add_reference(target)
    return _ResolvedNoteLinks(tuple(links), tuple(inline_notes), tuple(references))


def resolve_extra_note(
    target: MemoryNoteLinkTarget,
    *,
    project_root: Path,
    home_root: Path,
    project_name: str,
    notes: tuple[MemoryNote, ...],
    scoped_webs: tuple[ScopedMemoryWeb, ...],
    depth: int | None,
    seen_note_paths: frozenset[str],
    note_inline_context: _NoteInlineContext | None,
) -> ResolvedMemoryNote | None:
    """Resolve a cross-unit inline note, degrading invalid links to references."""
    try:
        return resolve_note_selector(
            _NoteSelector(raw=target.address, path=target.address),
            project_root=project_root,
            home_root=home_root,
            project_name=project_name,
            notes=notes,
            scoped_webs=scoped_webs,
            depth=depth,
            seen_note_paths=seen_note_paths,
            note_inline_context=note_inline_context,
        )
    except MemoryReadError:
        return None
