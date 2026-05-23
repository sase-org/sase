"""Data models used by the ``sase init memory`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MemoryChangeOperation = Literal["create", "update", "overwrite"]
MemoryWritePolicy = Literal["overwrite", "create_if_missing"]


@dataclass(frozen=True)
class SiblingMemoryEntry:
    name: str
    description: str


@dataclass(frozen=True)
class MemoryExpectedFile:
    path: Path
    content: str
    detail: str
    write_policy: MemoryWritePolicy = "overwrite"
    stale_operation: MemoryChangeOperation = "update"


@dataclass(frozen=True)
class MemoryFileChange:
    path: Path
    operation: MemoryChangeOperation
    detail: str = ""


@dataclass(frozen=True)
class MemoryRootPlan:
    root: Path
    changes: tuple[MemoryFileChange, ...]
    unreferenced: tuple[Path, ...]


@dataclass(frozen=True)
class MemoryRootResult:
    root: Path
    written_paths: tuple[Path, ...]
    unreferenced: tuple[Path, ...]
