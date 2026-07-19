"""Memory inventory graph discovery.

The inventory separates loaded ``@`` references from plain memory path mentions
so CLI rendering can explain what enters agent context.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from sase.memory.inventory_models import (
    INSTRUCTION_ROOT_FILENAMES,
    LOADED_INSTRUCTION_ROOT_FILENAMES,
    MemoryContextRoot,
    MemoryContextRootKind,
    MemoryEntryKind,
    MemoryEntryStatus,
    MemoryFileEntry,
    MemoryInventory,
    MemoryReference,
    MemoryStats,
    ParsedMemoryReference,
    ReferenceKind,
    ResolvedReference,
)
from sase.memory.inventory_reachability import (
    inlined_short_memory_files,
    unreferenced_memory_files_for_init,
)
from sase.memory.inventory_references import (
    context_roots,
    display_path_for_context,
    instruction_roots,
    is_memory_path,
    iter_memory_files,
    loaded_instruction_roots,
    references_from_file,
    stats_for_file,
    stats_for_text,
)
from sase.memory.paths import memory_read_root

__all__ = [
    "INSTRUCTION_ROOT_FILENAMES",
    "LOADED_INSTRUCTION_ROOT_FILENAMES",
    "MemoryContextRoot",
    "MemoryContextRootKind",
    "MemoryEntryKind",
    "MemoryEntryStatus",
    "MemoryFileEntry",
    "MemoryInventory",
    "MemoryReference",
    "MemoryStats",
    "ReferenceKind",
    "build_memory_inventory",
    "display_path_for_context",
    "stats_for_text",
    "unreferenced_memory_files_for_init",
]

_STATUS_SORT_ORDER: dict[MemoryEntryStatus, int] = {
    "loaded": 0,
    "referenced": 1,
    "missing": 2,
    "available": 3,
}


def _record_reference(
    references_by_target: dict[Path, list[MemoryReference]],
    *,
    root: Path,
    parsed: ParsedMemoryReference,
    source: Path,
    resolved: ResolvedReference,
) -> None:
    if not is_memory_path(root, resolved.target):
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
    inventory_context_roots = context_roots(root_resolved, home_root)
    memory_roots_by_root = {
        context_root.root: memory_read_root(
            context_root.root,
            label=f"{context_root.kind} memory",
        )
        for context_root in inventory_context_roots
    }
    memory_files_by_root = {
        context_root.root: set(
            iter_memory_files(
                context_root.root,
                source_memory_root=memory_roots_by_root[context_root.root],
            )
        )
        for context_root in inventory_context_roots
    }
    memory_files = {
        path for root_files in memory_files_by_root.values() for path in root_files
    }
    loaded_memory_files: set[Path] = set()
    inlined_short_files: set[Path] = set()
    loaded_instruction_files: set[Path] = set()
    references_by_target: dict[Path, list[MemoryReference]] = {}

    inventory_instruction_roots: list[Path] = []
    seen_instruction_roots: set[Path] = set()
    queue: deque[tuple[MemoryContextRoot, Path]] = deque()
    for context_root in inventory_context_roots:
        for instruction_root in instruction_roots(context_root.root):
            if instruction_root in seen_instruction_roots:
                continue
            seen_instruction_roots.add(instruction_root)
            inventory_instruction_roots.append(instruction_root)
        for instruction_root in loaded_instruction_roots(context_root.root):
            loaded_instruction_files.add(instruction_root)
            queue.append((context_root, instruction_root))
            for target in inlined_short_memory_files(
                context_root.root,
                instruction_root,
                overlay={},
                source_memory_root=memory_roots_by_root[context_root.root],
            ):
                if target in memory_files_by_root[context_root.root]:
                    inlined_short_files.add(target)

    visited: set[tuple[Path, Path]] = set()
    while queue:
        context_root, source_path = queue.popleft()
        source = source_path.resolve(strict=False)
        visit_key = (context_root.root, source)
        if visit_key in visited:
            continue
        visited.add(visit_key)

        for parsed, resolved in references_from_file(
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
        stats = stats_for_file(path) if exists else None
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
        elif path in inlined_short_files:
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
                relative_path=display_path_for_context(inventory_context_roots, path),
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
        instruction_roots=tuple(inventory_instruction_roots),
        entries=tuple(entries),
        loaded_stats=MemoryStats(
            line_count=loaded_line_count,
            approx_token_count=loaded_token_count,
        ),
        context_roots=inventory_context_roots,
    )
