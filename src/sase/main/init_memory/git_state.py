"""Pure git-status helpers for ``sase memory init``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class _PorcelainStatusEntry:
    """One ``git status --porcelain=v1 -z`` entry."""

    status: str
    path: str
    original_path: str | None = None


@dataclass(frozen=True)
class DirtyPath:
    """A repo-relative dirty path and its porcelain status."""

    path: str
    status: str


@dataclass(frozen=True)
class PreInitGitState:
    """Dirty state captured before memory init writes generated files."""

    git_root: Path
    memory_dirty: tuple[DirtyPath, ...]
    other_dirty: tuple[DirtyPath, ...]


def _decode_path(value: bytes | str) -> str:
    if isinstance(value, str):
        return value
    return os.fsdecode(value)


def parse_status_z(output: bytes | str) -> tuple[_PorcelainStatusEntry, ...]:
    """Parse NUL-delimited porcelain v1 status output."""
    if not output:
        return ()
    raw_parts: list[bytes | str] = []
    if isinstance(output, bytes):
        raw_parts.extend(output.split(b"\0"))
    else:
        raw_parts.extend(output.split("\0"))
    while raw_parts and raw_parts[-1] in (b"", ""):
        raw_parts.pop()

    entries: list[_PorcelainStatusEntry] = []
    index = 0
    while index < len(raw_parts):
        token = _decode_path(raw_parts[index])
        index += 1
        if len(token) < 3:
            raise ValueError(f"malformed git status entry: {token!r}")
        status = token[:2]
        path = token[3:]
        original_path: str | None = None
        if "R" in status or "C" in status:
            if index >= len(raw_parts):
                raise ValueError(f"missing source path for git status entry: {token!r}")
            original_path = _decode_path(raw_parts[index])
            index += 1
        entries.append(
            _PorcelainStatusEntry(
                status=status,
                path=path,
                original_path=original_path,
            )
        )
    return tuple(entries)


def _normalize_memory_rel(memory_rel: str | Path) -> str:
    normalized = Path(memory_rel).as_posix().strip("/")
    return normalized or "memory"


def _is_under(path: str, parent: str) -> bool:
    normalized = path.strip("/")
    return normalized == parent or normalized.startswith(f"{parent}/")


def _entry_dirty_paths(entry: _PorcelainStatusEntry) -> tuple[DirtyPath, ...]:
    paths = [DirtyPath(path=entry.path, status=entry.status)]
    if entry.original_path is not None:
        paths.append(DirtyPath(path=entry.original_path, status=entry.status))
    return tuple(paths)


def classify(
    entries: Iterable[_PorcelainStatusEntry],
    memory_rel: str | Path | Iterable[str | Path],
    *,
    source_paths: Iterable[str | Path] = (),
) -> tuple[tuple[DirtyPath, ...], tuple[DirtyPath, ...]]:
    """Partition dirty paths into foldable and unrelated buckets."""
    memory_prefixes: tuple[str, ...]
    if isinstance(memory_rel, (str, Path)):
        memory_prefixes = (_normalize_memory_rel(memory_rel),)
    else:
        memory_prefixes = tuple(_normalize_memory_rel(path) for path in memory_rel)
    source_keys = {
        Path(source_path).as_posix().strip("/") for source_path in source_paths
    }
    memory_dirty: list[DirtyPath] = []
    other_dirty: list[DirtyPath] = []
    seen: set[str] = set()
    for entry in entries:
        for dirty_path in _entry_dirty_paths(entry):
            if dirty_path.path in seen:
                continue
            seen.add(dirty_path.path)
            normalized_path = Path(dirty_path.path).as_posix().strip("/")
            if (
                any(
                    _is_under(normalized_path, memory_prefix)
                    for memory_prefix in memory_prefixes
                )
                or normalized_path in source_keys
            ):
                memory_dirty.append(dirty_path)
            else:
                other_dirty.append(dirty_path)
    return tuple(memory_dirty), tuple(other_dirty)


def partition_source_paths(
    dirty_paths: Iterable[DirtyPath],
    source_paths: Iterable[str | Path],
) -> tuple[tuple[DirtyPath, ...], tuple[DirtyPath, ...]]:
    """Partition already-captured paths by exact generated-source matches."""
    source_keys = {
        Path(source_path).as_posix().strip("/") for source_path in source_paths
    }
    matched: list[DirtyPath] = []
    unrelated: list[DirtyPath] = []
    for dirty_path in dirty_paths:
        normalized_path = Path(dirty_path.path).as_posix().strip("/")
        bucket = matched if normalized_path in source_keys else unrelated
        bucket.append(dirty_path)
    return tuple(matched), tuple(unrelated)


def dirty_path_label(status: str) -> str:
    """Return a compact human label for a porcelain status code."""
    if status == "??":
        return "new"
    if "U" in status:
        return "conflicted"
    if "R" in status:
        return "renamed"
    if "C" in status:
        return "copied"
    if "D" in status:
        return "deleted"
    if "A" in status:
        return "new"
    return "modified"
