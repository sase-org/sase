"""Memory inventory graph discovery.

The inventory separates loaded ``@`` references from plain memory path mentions
so CLI rendering can explain what enters agent context.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path
import re
from typing import Literal

from sase.memory.notes import AGENTS_PARENT, MemoryNote, parse_memory_note_text
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_note_relative_path,
    memory_read_root,
)

ReferenceKind = Literal["loaded", "plain"]
MemoryEntryStatus = Literal["loaded", "referenced", "available", "missing"]
MemoryEntryKind = Literal["memory", "instruction"]
MemoryContextRootKind = Literal["project", "home"]

INSTRUCTION_ROOT_FILENAMES = (
    "CLAUDE.md",
    # Antigravity CLI (`agy`) reads GEMINI.md for workspace context.
    "GEMINI.md",
    "QWEN.md",
    "OPENCODE.md",
    "AGENTS.md",
)
LOADED_INSTRUCTION_ROOT_FILENAMES = ("AGENTS.md",)

_AT_REF_RE = re.compile(r"(?:^|(?<=\s)|(?<=[\"'`(]))@([^\s,;:()[\]{}\"'`]+)")
_MEMORY_PATH_RE = re.compile(
    r"(?<![\w./-])((?:sase/)?memory/[^\s,;:()[\]{}\"'`/]+?\.md)"
)
_INLINED_SHORT_MEMORY_RE = re.compile(
    r"^###[ \t]+(?:.*[ \t])?\(([A-Za-z0-9_.-]+)\)[ \t]*$",
    re.MULTILINE,
)
_TRAILING_TOKEN_PUNCTUATION = ".,;:!?)"
_STATUS_SORT_ORDER: dict[MemoryEntryStatus, int] = {
    "loaded": 0,
    "referenced": 1,
    "missing": 2,
    "available": 3,
}


@dataclass(frozen=True)
class _ParsedMemoryReference:
    kind: ReferenceKind
    token: str


@dataclass(frozen=True)
class _MemoryStats:
    line_count: int
    approx_token_count: int


MemoryStats = _MemoryStats


@dataclass(frozen=True)
class MemoryReference:
    kind: ReferenceKind
    token: str
    source: Path
    target: Path
    exists: bool


@dataclass(frozen=True)
class MemoryFileEntry:
    path: Path
    relative_path: str
    status: MemoryEntryStatus
    stats: _MemoryStats | None
    references: tuple[MemoryReference, ...]
    kind: MemoryEntryKind = "memory"


@dataclass(frozen=True)
class MemoryContextRoot:
    root: Path
    kind: MemoryContextRootKind


@dataclass(frozen=True)
class MemoryInventory:
    root: Path
    instruction_roots: tuple[Path, ...]
    entries: tuple[MemoryFileEntry, ...]
    loaded_stats: _MemoryStats
    context_roots: tuple[MemoryContextRoot, ...] = ()

    @property
    def loaded_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "loaded")

    @property
    def referenced_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "referenced")

    @property
    def available_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "available")

    @property
    def missing_count(self) -> int:
        return sum(1 for entry in self.entries if entry.status == "missing")

    def entry_for(self, relative_path: str) -> MemoryFileEntry:
        for entry in self.entries:
            if entry.relative_path == relative_path:
                return entry
        raise KeyError(relative_path)


@dataclass(frozen=True)
class _ResolvedReference:
    target: Path
    exists: bool


def _normalize_overlay(overlay: Mapping[Path, str] | None) -> dict[Path, str]:
    if overlay is None:
        return {}
    return {path.resolve(strict=False): content for path, content in overlay.items()}


def _path_exists(path: Path, overlay: Mapping[Path, str]) -> bool:
    return path.resolve(strict=False) in overlay or path.is_file()


def _read_text(path: Path, overlay: Mapping[Path, str]) -> str | None:
    resolved = path.resolve(strict=False)
    if resolved in overlay:
        return overlay[resolved]
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _clean_token(token: str) -> str:
    return token.rstrip(_TRAILING_TOKEN_PUNCTUATION)


def _overlaps(span: tuple[int, int], spans: tuple[tuple[int, int], ...]) -> bool:
    start, end = span
    return any(
        start < other_end and other_start < end for other_start, other_end in spans
    )


def _parse_references(text: str) -> tuple[_ParsedMemoryReference, ...]:
    """Return typed reference tokens found in ``text``.

    ``@memory/foo.md`` is reported only as a loaded reference, not also as a
    plain memory-path mention.
    """
    references: list[tuple[int, _ParsedMemoryReference]] = []
    loaded_spans: list[tuple[int, int]] = []
    for match in _AT_REF_RE.finditer(text):
        token = _clean_token(match.group(1))
        if not token:
            continue
        loaded_spans.append(match.span(1))
        references.append(
            (match.start(1), _ParsedMemoryReference(kind="loaded", token=token))
        )

    loaded_span_tuple = tuple(loaded_spans)
    for match in _MEMORY_PATH_RE.finditer(text):
        if _overlaps(match.span(1), loaded_span_tuple):
            continue
        token = _clean_token(match.group(1))
        if not token:
            continue
        references.append(
            (match.start(1), _ParsedMemoryReference(kind="plain", token=token))
        )

    return tuple(
        reference for _, reference in sorted(references, key=lambda item: item[0])
    )


def _iter_memory_files(
    root: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    overlay_files = _normalize_overlay(overlay)
    memory_root = (
        source_memory_root.resolve(strict=False)
        if source_memory_root is not None
        else memory_read_root(root_resolved)
    )
    results: list[Path] = []
    if memory_root is not None and memory_root.exists():
        results.extend(
            path.resolve(strict=False)
            for path in memory_root.glob("*.md")
            if path.is_file() and path.name != "README.md"
        )
    results.extend(
        path
        for path in overlay_files
        if _inside_root(root_resolved, path) and _is_memory_path(root_resolved, path)
    )
    canonical_overlay_names = {
        path.name
        for path in overlay_files
        if path.parent == root_resolved / CANONICAL_MEMORY_RELATIVE_ROOT
    }
    results = [
        path
        for path in results
        if not (
            path.parent == root_resolved / "memory"
            and path.name in canonical_overlay_names
        )
    ]
    return tuple(sorted(set(results), key=lambda path: path.as_posix()))


def _instruction_roots(root: Path) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    roots: list[Path] = []
    for filename in INSTRUCTION_ROOT_FILENAMES:
        path = (root_resolved / filename).resolve(strict=False)
        if path.is_file():
            roots.append(path)
    return tuple(roots)


def _loaded_instruction_roots(root: Path) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    roots: list[Path] = []
    for filename in LOADED_INSTRUCTION_ROOT_FILENAMES:
        path = (root_resolved / filename).resolve(strict=False)
        if path.is_file():
            roots.append(path)
    return tuple(roots)


def _context_roots(
    project_root: Path, home_root: Path | None
) -> tuple[MemoryContextRoot, ...]:
    project_root_resolved = project_root.resolve(strict=False)
    roots = [
        MemoryContextRoot(root=project_root_resolved, kind="project"),
    ]
    if home_root is None:
        return tuple(roots)

    home_root_resolved = home_root.expanduser().resolve(strict=False)
    if home_root_resolved != project_root_resolved:
        roots.append(MemoryContextRoot(root=home_root_resolved, kind="home"))
    return tuple(roots)


def _candidate_paths(root: Path, source: Path, token: str) -> tuple[Path, ...]:
    expanded = Path(token).expanduser()
    if expanded.is_absolute():
        return (expanded,)

    if token.startswith(("./", "../")):
        return (source.parent / expanded,)
    return (root / expanded, source.parent / expanded)


def _inside_root(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_memory_path(root: Path, path: Path) -> bool:
    if path.suffix != ".md":
        return False
    try:
        root_relative = path.relative_to(root)
    except ValueError:
        return False
    relative = memory_note_relative_path(root_relative)
    if relative is None:
        return False
    return len(relative.parts) == 1 and relative.name != "README.md"


def display_path_for_context(
    context_roots: tuple[MemoryContextRoot, ...], path: Path
) -> str:
    """Return the user-facing path for ``path`` within an inventory."""
    resolved = path.resolve(strict=False)
    for context_root in context_roots:
        try:
            relative = resolved.relative_to(context_root.root)
        except ValueError:
            continue

        relative_text = relative.as_posix()
        if relative_text == ".":
            return "~" if context_root.kind == "home" else "."
        if context_root.kind == "home":
            return f"~/{relative_text}"
        return relative_text
    return resolved.as_posix()


def _resolve_reference(
    root: Path,
    source: Path,
    token: str,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> _ResolvedReference | None:
    """Resolve ``token`` using init-memory root containment rules."""
    if token.startswith(("http://", "https://")):
        return None

    overlay_files = _normalize_overlay(overlay)
    root_resolved = root.resolve(strict=False)
    source_resolved = source.resolve(strict=False)
    in_root_candidates: list[Path] = []
    candidates = list(_candidate_paths(root_resolved, source_resolved, token))
    memory_relative = memory_note_relative_path(Path(token))
    if memory_relative is not None:
        selected_memory_root = source_memory_root or memory_read_root(root_resolved)
        if selected_memory_root is not None:
            candidates.insert(1, selected_memory_root / memory_relative)
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if not _inside_root(root_resolved, resolved):
            continue
        if _path_exists(resolved, overlay_files):
            return _ResolvedReference(target=resolved, exists=True)
        in_root_candidates.append(resolved)

    if not in_root_candidates:
        return None
    return _ResolvedReference(target=in_root_candidates[0], exists=False)


def _references_from_file(
    root: Path,
    source: Path,
    *,
    overlay: Mapping[Path, str] | None = None,
    source_memory_root: Path | None = None,
) -> tuple[tuple[_ParsedMemoryReference, _ResolvedReference], ...]:
    overlay_files = _normalize_overlay(overlay)
    text = _read_text(source, overlay_files)
    if text is None:
        return ()

    resolved: list[tuple[_ParsedMemoryReference, _ResolvedReference]] = []
    for parsed in _parse_references(text):
        target = _resolve_reference(
            root,
            source,
            parsed.token,
            overlay=overlay_files,
            source_memory_root=source_memory_root,
        )
        if target is None:
            continue
        resolved.append((parsed, target))
    return tuple(resolved)


def _stats_for_text(text: str) -> _MemoryStats:
    return _MemoryStats(
        line_count=len(text.splitlines()),
        approx_token_count=ceil(len(text) / 4) if text else 0,
    )


def stats_for_text(text: str) -> MemoryStats:
    return _stats_for_text(text)


def _stats_for_file(path: Path) -> _MemoryStats | None:
    try:
        return _stats_for_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _memory_note_for_init(
    root: Path,
    path: Path,
    *,
    overlay: Mapping[Path, str],
) -> MemoryNote | None:
    text = _read_text(path, overlay)
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


def _inlined_short_memory_files(
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
    text = _read_text(source, overlay)
    if text is None:
        return ()
    targets: list[Path] = []
    for match in _INLINED_SHORT_MEMORY_RE.finditer(text):
        token = f"sase/memory/{match.group(1)}.md"
        resolved = _resolve_reference(
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


def _record_reference(
    references_by_target: dict[Path, list[MemoryReference]],
    *,
    root: Path,
    parsed: _ParsedMemoryReference,
    source: Path,
    resolved: _ResolvedReference,
) -> None:
    if not _is_memory_path(root, resolved.target):
        return
    references_by_target.setdefault(resolved.target, []).append(
        MemoryReference(
            kind=parsed.kind,
            token=parsed.token,
            source=source,
            target=resolved.target,
            exists=resolved.exists,
        )
    )


def build_memory_inventory(
    root: Path | None = None, *, home_root: Path | None = None
) -> MemoryInventory:
    root_resolved = (Path.cwd() if root is None else root).resolve(strict=False)
    context_roots = _context_roots(root_resolved, home_root)
    memory_roots_by_root = {
        context_root.root: memory_read_root(
            context_root.root,
            label=f"{context_root.kind} memory",
        )
        for context_root in context_roots
    }
    memory_files_by_root = {
        context_root.root: set(
            _iter_memory_files(
                context_root.root,
                source_memory_root=memory_roots_by_root[context_root.root],
            )
        )
        for context_root in context_roots
    }
    memory_files = {
        path for root_files in memory_files_by_root.values() for path in root_files
    }
    loaded_memory_files: set[Path] = set()
    inlined_short_memory_files: set[Path] = set()
    loaded_instruction_files: set[Path] = set()
    references_by_target: dict[Path, list[MemoryReference]] = {}

    instruction_roots: list[Path] = []
    seen_instruction_roots: set[Path] = set()
    queue: deque[tuple[MemoryContextRoot, Path]] = deque()
    for context_root in context_roots:
        for instruction_root in _instruction_roots(context_root.root):
            if instruction_root in seen_instruction_roots:
                continue
            seen_instruction_roots.add(instruction_root)
            instruction_roots.append(instruction_root)
        for instruction_root in _loaded_instruction_roots(context_root.root):
            loaded_instruction_files.add(instruction_root)
            queue.append((context_root, instruction_root))
            for target in _inlined_short_memory_files(
                context_root.root,
                instruction_root,
                overlay={},
                source_memory_root=memory_roots_by_root[context_root.root],
            ):
                if target in memory_files_by_root[context_root.root]:
                    inlined_short_memory_files.add(target)

    visited: set[tuple[Path, Path]] = set()
    while queue:
        context_root, source_path = queue.popleft()
        source = source_path.resolve(strict=False)
        visit_key = (context_root.root, source)
        if visit_key in visited:
            continue
        visited.add(visit_key)

        for parsed, resolved in _references_from_file(
            context_root.root,
            source,
            source_memory_root=memory_roots_by_root[context_root.root],
        ):
            if parsed.kind == "loaded":
                _record_reference(
                    references_by_target,
                    root=context_root.root,
                    parsed=parsed,
                    source=source,
                    resolved=resolved,
                )
                if resolved.exists:
                    if resolved.target in memory_files_by_root[context_root.root]:
                        loaded_memory_files.add(resolved.target)
                    queue.append((context_root, resolved.target))
                continue

            _record_reference(
                references_by_target,
                root=context_root.root,
                parsed=parsed,
                source=source,
                resolved=resolved,
            )

    loaded_line_count = 0
    loaded_token_count = 0
    entries: list[MemoryFileEntry] = []
    entry_paths = (
        set(memory_files) | set(references_by_target) | loaded_instruction_files
    )
    for path in entry_paths:
        is_instruction = path in loaded_instruction_files
        exists = (path in memory_files or is_instruction) and path.is_file()
        stats = _stats_for_file(path) if exists else None
        references = tuple(references_by_target.get(path, ()))
        status: MemoryEntryStatus
        if is_instruction:
            status = "loaded"
            if stats is not None:
                loaded_line_count += stats.line_count
                loaded_token_count += stats.approx_token_count
        elif path in loaded_memory_files:
            status = "loaded"
            if stats is not None:
                loaded_line_count += stats.line_count
                loaded_token_count += stats.approx_token_count
        elif path in inlined_short_memory_files:
            # Inlined short notes are loaded as part of their ``AGENTS.md``; their
            # bytes are already counted via that loaded instruction file, so they
            # contribute their status but not their stats.
            status = "loaded"
        elif not exists:
            status = "missing"
        elif references:
            status = "referenced"
        else:
            status = "available"
        entries.append(
            MemoryFileEntry(
                path=path,
                relative_path=display_path_for_context(context_roots, path),
                status=status,
                stats=stats,
                references=references,
                kind="instruction" if is_instruction else "memory",
            )
        )

    entries.sort(
        key=lambda entry: (
            _STATUS_SORT_ORDER[entry.status],
            entry.relative_path,
        )
    )
    return MemoryInventory(
        root=root_resolved,
        instruction_roots=tuple(instruction_roots),
        entries=tuple(entries),
        loaded_stats=_MemoryStats(
            line_count=loaded_line_count,
            approx_token_count=loaded_token_count,
        ),
        context_roots=context_roots,
    )


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
    overlay_files = _normalize_overlay(overlay)
    agents_path = (root_resolved / "AGENTS.md").resolve(strict=False)
    if not _path_exists(agents_path, overlay_files):
        return ()

    memory_files = set(
        _iter_memory_files(
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
        for _, resolved in _references_from_file(
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
            for _, resolved in _references_from_file(
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
    overlay_files = _normalize_overlay(overlay)
    memory_files = set(
        _iter_memory_files(
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
