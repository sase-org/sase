"""Shared models for audited ``sase memory read`` access."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.memory.notes import MemoryNote

READ_LOG_SCHEMA_VERSION = 2

MemoryReadKind = Literal["note", "web", "strand"]


class MemoryReadError(ValueError):
    """Base class for memory-read validation errors."""


class MemoryReadPathError(MemoryReadError):
    """Raised when a memory-relative read path is not allowed."""


@dataclass(frozen=True)
class ValidatedMemoryPath:
    """A memory file path that has passed read-path validation."""

    memory_root: Path
    allowed_root: Path
    canonical_path: str
    path: Path
    resolved_path: Path
    note: MemoryNote
    content_root: Path


@dataclass(frozen=True)
class FrontmatterStripResult:
    body: str
    stripped: bool


@dataclass(frozen=True)
class MemoryReadContent:
    path: ValidatedMemoryPath
    raw_text: str
    body: str
    byte_count: int
    frontmatter_stripped: bool


@dataclass(frozen=True)
class MemoryReadEvent:
    """One audited ``sase memory read`` event.

    ``canonical_path``/``resolved_path``/``byte_count``/``frontmatter_stripped``
    keep their pre-web meaning exactly for a single-note read: every consumer
    written before webs existed (the ACE memory-reads loader, ``memory log``)
    keeps working unchanged. ``kind``/``selectors``/``resolved_targets``/
    ``included_targets``/``depth``/``scope_origin`` generalize the event to
    also describe a web or strand batch; for a single-note read they default
    to the note-only values below. For a batch, ``canonical_path`` and
    ``resolved_path`` fall back to the first resolved target so old
    consumers still show something reasonable rather than an empty field.
    """

    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    canonical_path: str
    resolved_path: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    reason: str
    byte_count: int
    frontmatter_stripped: bool
    kind: MemoryReadKind = "note"
    selectors: tuple[str, ...] = ()
    resolved_targets: tuple[str, ...] = ()
    included_targets: tuple[str, ...] = ()
    depth: int | None = None
    scope_origin: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MemoryReadPathSummary:
    canonical_path: str
    read_count: int
    distinct_agent_count: int
    last_read_at: str
    last_agent: str
    last_reason: str


@dataclass(frozen=True)
class MemoryReadAgentSummary:
    agent_name: str
    read_count: int
    distinct_path_count: int
    last_read_at: str
    last_path: str
    last_reason: str


__all__ = [
    "READ_LOG_SCHEMA_VERSION",
    "FrontmatterStripResult",
    "MemoryReadAgentSummary",
    "MemoryReadContent",
    "MemoryReadError",
    "MemoryReadEvent",
    "MemoryReadKind",
    "MemoryReadPathError",
    "MemoryReadPathSummary",
    "ValidatedMemoryPath",
]
