"""Memory inventory graph discovery.

The inventory separates loaded ``@`` references from plain memory path mentions
so CLI rendering can explain what enters agent context without changing the
legacy init-memory reachability checks.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from math import ceil
from pathlib import Path
import re
from typing import Literal

ReferenceKind = Literal["loaded", "plain"]
MemoryEntryStatus = Literal["loaded", "referenced", "available", "missing"]

INSTRUCTION_ROOT_FILENAMES = (
    "CLAUDE.md",
    "GEMINI.md",
    "QWEN.md",
    "OPENCODE.md",
    "AGENTS.md",
)

_AT_REF_RE = re.compile(r"(?:^|(?<=\s)|(?<=[\"'`(]))@([^\s,;:()[\]{}\"'`]+)")
_MEMORY_PATH_RE = re.compile(
    r"(?<![\w./-])(memory/(?:short|long)/[^\s,;:()[\]{}\"'`]+?\.md)"
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


@dataclass(frozen=True)
class MemoryInventory:
    root: Path
    instruction_roots: tuple[Path, ...]
    entries: tuple[MemoryFileEntry, ...]
    loaded_stats: _MemoryStats

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

    ``@memory/short/foo.md`` is reported only as a loaded reference, not also as
    a plain memory-path mention.
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
    root: Path, *, overlay: Mapping[Path, str] | None = None
) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    overlay_files = _normalize_overlay(overlay)
    memory_root = root_resolved / "memory"
    results: list[Path] = []
    for tier in ("short", "long"):
        tier_root = memory_root / tier
        if not tier_root.exists():
            continue
        results.extend(
            path.resolve(strict=False)
            for path in tier_root.rglob("*.md")
            if path.is_file()
        )
    results.extend(
        path
        for path in overlay_files
        if _inside_root(root_resolved, path) and _is_memory_path(root_resolved, path)
    )
    return tuple(sorted(set(results), key=lambda path: path.as_posix()))


def _instruction_roots(root: Path) -> tuple[Path, ...]:
    root_resolved = root.resolve(strict=False)
    roots: list[Path] = []
    for filename in INSTRUCTION_ROOT_FILENAMES:
        path = (root_resolved / filename).resolve(strict=False)
        if path.is_file():
            roots.append(path)
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
    memory_root = root / "memory"
    for tier in ("short", "long"):
        try:
            path.relative_to(memory_root / tier)
        except ValueError:
            continue
        return True
    return False


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _resolve_reference(
    root: Path,
    source: Path,
    token: str,
    *,
    overlay: Mapping[Path, str] | None = None,
) -> _ResolvedReference | None:
    """Resolve ``token`` using the legacy init-memory root containment rules."""
    if token.startswith(("http://", "https://")):
        return None

    overlay_files = _normalize_overlay(overlay)
    root_resolved = root.resolve(strict=False)
    source_resolved = source.resolve(strict=False)
    in_root_candidates: list[Path] = []
    for candidate in _candidate_paths(root_resolved, source_resolved, token):
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


def _stats_for_file(path: Path) -> _MemoryStats | None:
    try:
        return _stats_for_text(path.read_text(encoding="utf-8"))
    except OSError:
        return None


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


def build_memory_inventory(root: Path | None = None) -> MemoryInventory:
    root_resolved = (Path.cwd() if root is None else root).resolve(strict=False)
    memory_files = set(_iter_memory_files(root_resolved))
    loaded_memory_files: set[Path] = set()
    references_by_target: dict[Path, list[MemoryReference]] = {}

    queue: deque[Path] = deque(_instruction_roots(root_resolved))
    visited: set[Path] = set()
    while queue:
        source = queue.popleft().resolve(strict=False)
        if source in visited:
            continue
        visited.add(source)

        for parsed, resolved in _references_from_file(root_resolved, source):
            if parsed.kind == "loaded":
                _record_reference(
                    references_by_target,
                    root=root_resolved,
                    parsed=parsed,
                    source=source,
                    resolved=resolved,
                )
                if resolved.exists:
                    if resolved.target in memory_files:
                        loaded_memory_files.add(resolved.target)
                    queue.append(resolved.target)
                continue

            _record_reference(
                references_by_target,
                root=root_resolved,
                parsed=parsed,
                source=source,
                resolved=resolved,
            )

    loaded_line_count = 0
    loaded_token_count = 0
    entries: list[MemoryFileEntry] = []
    entry_paths = set(memory_files) | set(references_by_target)
    for path in entry_paths:
        exists = path in memory_files and path.is_file()
        stats = _stats_for_file(path) if exists else None
        references = tuple(references_by_target.get(path, ()))
        if path in loaded_memory_files:
            status: MemoryEntryStatus = "loaded"
            if stats is not None:
                loaded_line_count += stats.line_count
                loaded_token_count += stats.approx_token_count
        elif not exists:
            status = "missing"
        elif references:
            status = "referenced"
        else:
            status = "available"
        entries.append(
            MemoryFileEntry(
                path=path,
                relative_path=_relative_path(root_resolved, path),
                status=status,
                stats=stats,
                references=references,
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
        instruction_roots=_instruction_roots(root_resolved),
        entries=tuple(entries),
        loaded_stats=_MemoryStats(
            line_count=loaded_line_count,
            approx_token_count=loaded_token_count,
        ),
    )


def _reachable_memory_files_for_init(
    root: Path, *, overlay: Mapping[Path, str] | None = None
) -> tuple[Path, ...]:
    """Return legacy init-memory reachability from ``AGENTS.md``.

    This intentionally follows both ``@`` and plain memory path references so
    existing ``sase init memory`` validation remains backward-compatible.
    """
    root_resolved = root.resolve(strict=False)
    overlay_files = _normalize_overlay(overlay)
    agents_path = (root_resolved / "AGENTS.md").resolve(strict=False)
    if not _path_exists(agents_path, overlay_files):
        return ()

    memory_files = set(_iter_memory_files(root_resolved, overlay=overlay_files))
    reachable: set[Path] = set()
    visited: set[Path] = {agents_path}
    queue: deque[Path] = deque(
        resolved.target
        for _, resolved in _references_from_file(
            root_resolved,
            agents_path,
            overlay=overlay_files,
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
        queue.extend(
            resolved.target
            for _, resolved in _references_from_file(
                root_resolved,
                path,
                overlay=overlay_files,
            )
            if resolved.exists
        )

    return tuple(sorted(reachable, key=lambda path: path.as_posix()))


def unreferenced_memory_files_for_init(
    root: Path, *, overlay: Mapping[Path, str] | None = None
) -> tuple[Path, ...]:
    overlay_files = _normalize_overlay(overlay)
    memory_files = set(_iter_memory_files(root, overlay=overlay_files))
    reachable = set(_reachable_memory_files_for_init(root, overlay=overlay_files))
    return tuple(sorted(memory_files - reachable, key=lambda path: path.as_posix()))
