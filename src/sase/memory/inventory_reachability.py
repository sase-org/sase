"""Init-time reachability validation for memory notes."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
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


def _is_inlined_memory_note(
    root: Path,
    path: Path,
    *,
    overlay: Mapping[Path, str],
) -> bool:
    """Return whether the memory file at *path* is inlined into agent docs."""
    note = _memory_note_for_init(root, path, overlay=overlay)
    return note is not None and (note.type == "core" or note.is_web_descriptor)


def inlined_short_memory_files(
    root: Path,
    source: Path,
    *,
    overlay: Mapping[Path, str],
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    """Return core notes inlined as ``### [N. ]Title (file)`` sections.

    ``sase memory init`` inlines each core note's body under such a header, so a
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
            and _is_inlined_memory_note(root, resolved.target, overlay=overlay)
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
        if note.type != "reference" or note.parent == AGENTS_PARENT:
            continue

        parent_path = path_by_reference.get(note.parent)
        if parent_path is None:
            continue
        parent_note = notes_by_path.get(parent_path)
        if parent_note is None or parent_note.type != "reference":
            continue
        children_by_parent.setdefault(parent_path, []).append(path)

    return {
        parent: tuple(sorted(children, key=lambda path: path.as_posix()))
        for parent, children in children_by_parent.items()
    }


def _memory_notes_by_path_for_init(
    root: Path,
    *,
    overlay: Mapping[Path, str],
    source_memory_root: Path | None = None,
    ignored_paths: Iterable[Path] = (),
) -> dict[Path, MemoryNote]:
    root_resolved = root.resolve(strict=False)
    memory_files = set(
        iter_memory_files(
            root_resolved,
            overlay=overlay,
            source_memory_root=source_memory_root,
        )
    )
    ignored_resolved = {path.resolve(strict=False) for path in ignored_paths}
    memory_files -= ignored_resolved
    return {
        path: note
        for path in memory_files
        if (note := _memory_note_for_init(root_resolved, path, overlay=overlay))
        is not None
    }


def _memory_parent_cycle_blockers(edges: Mapping[str, str]) -> tuple[str, ...]:
    blockers: list[str] = []
    visited: set[str] = set()
    reported: set[frozenset[str]] = set()
    for start in sorted(edges):
        path: list[str] = []
        path_indexes: dict[str, int] = {}
        node = start
        while node in edges:
            if node in path_indexes:
                cycle = path[path_indexes[node] :]
                key = frozenset(cycle)
                if key not in reported:
                    blockers.append(
                        "memory parent cycle detected: "
                        + " -> ".join((*cycle, cycle[0]))
                    )
                    reported.add(key)
                break
            if node in visited:
                break
            path_indexes[node] = len(path)
            path.append(node)
            node = edges[node]
        visited.update(path)
    return tuple(blockers)


def memory_parent_blockers_for_init(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
    ignored_paths: Iterable[Path] = (),
) -> tuple[str, ...]:
    """Return blockers for invalid memory-note parent relationships."""
    root_resolved = root.resolve(strict=False)
    overlay_files = normalize_overlay(overlay)
    notes_by_path = _memory_notes_by_path_for_init(
        root_resolved,
        overlay=overlay_files,
        source_memory_root=source_memory_root,
        ignored_paths=ignored_paths,
    )
    path_by_reference = {
        note.relative_path: path for path, note in notes_by_path.items()
    }
    blockers: list[str] = []
    parent_edges: dict[str, str] = {}

    for _path, note in sorted(
        notes_by_path.items(), key=lambda item: item[1].relative_path
    ):
        if note.parent == AGENTS_PARENT:
            continue
        if note.parent == note.relative_path:
            blockers.append(
                f"{root_resolved}: invalid memory parent for {note.relative_path}: "
                f"{note.parent} (parent points to the note itself)"
            )
            continue

        parent_path = path_by_reference.get(note.parent)
        if parent_path is None:
            blockers.append(
                f"{root_resolved}: invalid memory parent for {note.relative_path}: "
                f"{note.parent} (parent target does not exist)"
            )
            continue

        parent_note = notes_by_path[parent_path]
        if parent_note.type == "core":
            blockers.append(
                f"{root_resolved}: invalid memory parent for {note.relative_path}: "
                f"{note.parent} (parent target is a core memory note)"
            )
            continue
        if parent_note.type != "reference":
            blockers.append(
                f"{root_resolved}: invalid memory parent for {note.relative_path}: "
                f"{note.parent} (parent target is not a reference memory note)"
            )
            continue

        parent_edges[note.relative_path] = parent_note.relative_path

    return (*tuple(blockers), *_memory_parent_cycle_blockers(parent_edges))


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
    # Core notes and memory-web descriptors are inlined into ``AGENTS.md`` rather
    # than ``@``-imported, so they are inherently reachable; treat them as such
    # explicitly instead of relying on generated headers to look like memory path
    # references.
    reachable: set[Path] = {
        path
        for path in memory_files
        if _is_inlined_memory_note(root_resolved, path, overlay=overlay_files)
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
    ignored_paths: Iterable[Path] = (),
) -> tuple[Path, ...]:
    overlay_files = normalize_overlay(overlay)
    memory_files = set(
        iter_memory_files(
            root,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
    )
    ignored_resolved = {path.resolve(strict=False) for path in ignored_paths}
    memory_files -= ignored_resolved
    reachable = set(
        _reachable_memory_files_for_init(
            root,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
    )
    return tuple(sorted(memory_files - reachable, key=lambda path: path.as_posix()))
