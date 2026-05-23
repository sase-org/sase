"""Data models used by the ``sase init memory`` command."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SiblingMemoryEntry:
    name: str
    description: str


@dataclass(frozen=True)
class MemoryRootResult:
    root: Path
    written_paths: tuple[Path, ...]
    unreferenced: tuple[Path, ...]
