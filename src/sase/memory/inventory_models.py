"""Data models shared by memory inventory discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.amd.constants import (
    AGENTS_FILENAME,
    AGENTS_TEMPLATE_FILENAME,
    RECOGNIZED_PROVIDER_SHIM_FILES,
)

ReferenceKind = Literal["loaded", "plain"]
MemoryEntryStatus = Literal["loaded", "referenced", "available", "missing"]
MemoryEntryKind = Literal["memory", "instruction"]
MemoryContextRootKind = Literal["project", "home"]

# Recognition list: leftover GEMINI.md / QWEN.md / OPENCODE.md copies still
# count as instruction roots. agy 1.4.0 reads both GEMINI.md and AGENTS.md.
INSTRUCTION_ROOT_FILENAMES = (
    *RECOGNIZED_PROVIDER_SHIM_FILES,
    AGENTS_FILENAME,
    AGENTS_TEMPLATE_FILENAME,
)
LOADED_INSTRUCTION_ROOT_FILENAMES = (AGENTS_FILENAME, AGENTS_TEMPLATE_FILENAME)


@dataclass(frozen=True)
class ParsedMemoryReference:
    kind: ReferenceKind
    token: str


@dataclass(frozen=True)
class MemoryStats:
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
    stats: MemoryStats | None
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
    loaded_stats: MemoryStats
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
class ResolvedReference:
    target: Path
    exists: bool
