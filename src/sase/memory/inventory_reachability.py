"""Init-time reachability validation for memory notes."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
import re

from sase.memory.inventory_references import (
    iter_memory_files,
    normalize_overlay,
    path_exists,
    read_text,
    references_from_file,
    resolve_reference,
)
from sase.memory.notes import AGENTS_PARENT, MemoryNote, parse_memory_note_text
from sase.memory.paths import canonical_memory_reference

_INLINED_SHORT_MEMORY_RE = re.compile(
    r"^###[ \t]+(?:.*[ \t])?\(([A-Za-z0-9_.-]+)\)[ \t]*$",
    re.MULTILINE,
)


def _memory_note_for_init(
    root: Path,
    path: Path,
    *,
    overlay: Mapping[Path, str],
) -> MemoryNote | None:
    text = read_text(path, overlay)
    if text is None:
        return None
    try:
        relative_path = path.resolve(strict=False).relative_to(root)
    except ValueError:
        return None
    note = parse_memory_note_text(
        text,
        canonical_memory_reference(relative_path),
    )
    return replace(
        note,
        parent=canonical_memory_reference(note.parent).as_posix(),
        source_path=relative_path,
    )


def _is_short_memory_note(
    root: Path,
    path: Path,
    *,
    overlay: Mapping[Path, str],
) -> bool:
    """Return whether the memory file at *path* is a ``type: short`` note."""
    note = _memory_note_for_init(root, path, overlay=overlay)
    return note is not None and note.type == "short"


def inlined_short_memory_files(
    root: Path,
    source: Path,
    *,
    overlay: Mapping[Path, str],
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    """Return short notes inlined as ``### [N. ]Title (file)`` sections.

    ``sase memory init`` inlines each short note's body under such a header, so a
    note reached this way has its bytes loaded as part of *source* (an
    ``AGENTS.md``) even though there is no ``@`` import.
    """
    text = read_text(source, overlay)
    if text is None:
        return ()
    targets: list[Path] = []
    for match in _INLINED_SHORT_MEMORY_RE.finditer(text):
        token = f"sase/memory/{match.group(1)}.md"
        resolved = resolve_reference(
            root,
            source,
            token,
            overlay=overlay,
            source_memory_root=source_memory_root,
        )
        if (
            resolved is not None
            and resolved.exists
            and _is_short_memory_note(root, resolved.target, overlay=overlay)
        ):
            targets.append(resolved.target)
    return tuple(targets)


def _children_by_parent_for_init(
    root: Path,
    memory_files: set[Path],
    *,
    overlay: Mapping[Path, str],
) -> dict[Path, tuple[Path, ...]]:
    notes_by_path = {
        path: note
        for path in memory_files
        if (note := _memory_note_for_init(root, path, overlay=overlay)) is not None
    }
    path_by_reference = {
        note.relative_path: path for path, note in notes_by_path.items()
    }
    children_by_parent: dict[Path, list[Path]] = {}
    for path, note in notes_by_path.items():
        if note.type != "long" or note.parent == AGENTS_PARENT:
            continue

        parent_path = path_by_reference.get(note.parent)
        if parent_path is None:
            continue
        parent_note = notes_by_path.get(parent_path)
        if parent_note is None or parent_note.type != "long":
            continue
        children_by_parent.setdefault(parent_path, []).append(path)

    return {
        parent: tuple(sorted(children, key=lambda path: path.as_posix()))
        for parent, children in children_by_parent.items()
    }


def _reachable_memory_files_for_init(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    """Return init-memory reachability from ``AGENTS.md``.

    This intentionally follows both ``@`` and plain memory path references so
    ``sase init memory`` validation can catch unreachable files.
    """
    root_resolved = root.resolve(strict=False)
    overlay_files = normalize_overlay(overlay)
    agents_path = (root_resolved / "AGENTS.md").resolve(strict=False)
    if not path_exists(agents_path, overlay_files):
        return ()

    memory_files = set(
        iter_memory_files(
            root_resolved,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
    )
    child_memory_files = _children_by_parent_for_init(
        root_resolved,
        memory_files,
        overlay=overlay_files,
    )
    # Short notes are always inlined into ``AGENTS.md`` rather than ``@``-imported,
    # so they are inherently reachable; treat them as such explicitly instead of
    # relying on generated headers to look like memory path references.
    reachable: set[Path] = {
        path
        for path in memory_files
        if _is_short_memory_note(root_resolved, path, overlay=overlay_files)
    }
    visited: set[Path] = {agents_path}
    queue: deque[Path] = deque(
        resolved.target
        for _, resolved in references_from_file(
            root_resolved,
            agents_path,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
        if resolved.exists
    )

    while queue:
        path = queue.popleft().resolve(strict=False)
        if path in visited:
            continue
        visited.add(path)
        if path in memory_files:
            reachable.add(path)
            queue.extend(child_memory_files.get(path, ()))
        queue.extend(
            resolved.target
            for _, resolved in references_from_file(
                root_resolved,
                path,
                overlay=overlay_files,
                source_memory_root=source_memory_root,
            )
            if resolved.exists
        )

    return tuple(sorted(reachable, key=lambda path: path.as_posix()))


def unreferenced_memory_files_for_init(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    overlay_files = normalize_overlay(overlay)
    memory_files = set(
        iter_memory_files(
            root,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
    )
    reachable = set(
        _reachable_memory_files_for_init(
            root,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
    )
    return tuple(sorted(memory_files - reachable, key=lambda path: path.as_posix()))
