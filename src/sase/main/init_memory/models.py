"""Data models used by the ``sase memory init`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MemoryChangeOperation = Literal["create", "update", "overwrite", "delete"]
MemoryExpectedContent = str | bytes
MemoryWritePolicy = Literal["overwrite", "create_if_missing"]


@dataclass(frozen=True)
class LinkedRepoMemoryEntry:
    name: str
    description: str
    path: str | None = None
    auto_clone: bool = False


@dataclass(frozen=True)
class MemoryExpectedFile:
    path: Path
    content: MemoryExpectedContent
    detail: str
    write_policy: MemoryWritePolicy = "overwrite"
    stale_operation: MemoryChangeOperation = "update"


@dataclass(frozen=True)
class MemoryFileChange:
    path: Path
    operation: MemoryChangeOperation
    detail: str = ""
    new_content: MemoryExpectedContent | None = None


@dataclass(frozen=True)
class MemoryRootPlan:
    root: Path
    changes: tuple[MemoryFileChange, ...]
    unreferenced: tuple[Path, ...]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryRootResult:
    root: Path
    written_paths: tuple[Path, ...]
    unreferenced: tuple[Path, ...]
    deleted_paths: tuple[Path, ...] = ()
    fold_source_paths: tuple[Path, ...] = ()
