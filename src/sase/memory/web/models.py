"""Domain models for file-backed memory webs and strands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.memory.notes import (
    DEFAULT_MEMORY_LINK_REFERENCE,
    DEFAULT_MEMORY_LINK_RENDERING,
    DEFAULT_MEMORY_PRIORITY,
    MemoryLinkReference,
    MemoryLinkRendering,
)

WebRosterStyle = Literal["inline", "list"]
WebClosureMode = Literal["none", "mentions"]
WebScope = Literal["project", "home"]
WebSource = Literal["file", "generated"]


@dataclass(frozen=True)
class MemoryStrand:
    """One small note inside a memory web."""

    root: Path
    memory_root: Path
    web_slug: str
    slug: str
    path: Path
    relative_path: str
    keyword: str
    aliases: tuple[str, ...]
    summary: str | None
    metadata: dict[str, Any]
    body: str
    raw_text: str
    body_start: int
    frontmatter: dict[str, Any]
    link_reference: MemoryLinkReference = DEFAULT_MEMORY_LINK_REFERENCE
    link_rendering: MemoryLinkRendering = DEFAULT_MEMORY_LINK_RENDERING


@dataclass(frozen=True)
class MemoryWeb:
    """A flat descriptor note plus its sibling strand directory."""

    root: Path
    memory_root: Path
    slug: str
    path: Path
    relative_path: str
    description: str | None
    roster: WebRosterStyle
    roster_label: str
    strand_noun: str
    closure: WebClosureMode
    metadata: dict[str, Any]
    body: str
    raw_text: str
    body_start: int
    frontmatter: dict[str, Any]
    priority: int = DEFAULT_MEMORY_PRIORITY
    strands: tuple[MemoryStrand, ...] = ()
    source: WebSource = "file"
    link_reference: MemoryLinkReference = DEFAULT_MEMORY_LINK_REFERENCE
    link_rendering: MemoryLinkRendering = DEFAULT_MEMORY_LINK_RENDERING


@dataclass(frozen=True)
class MemoryWebDiscoveryIssue:
    """A filesystem or parsing problem found while discovering webs."""

    code: str
    path: Path
    message: str


@dataclass(frozen=True)
class MemoryWebDiscovery:
    """Provider discovery output for one memory root."""

    root: Path
    memory_root: Path | None
    webs: tuple[MemoryWeb, ...]
    issues: tuple[MemoryWebDiscoveryIssue, ...] = ()


@dataclass(frozen=True)
class WebStrandOrigin:
    """Which scope supplied one effective strand."""

    scope: WebScope
    strand: MemoryStrand


@dataclass(frozen=True)
class ScopedMemoryWeb:
    """A project-over-home merged web view for read-time lookup."""

    slug: str
    web: MemoryWeb
    strands: tuple[MemoryStrand, ...]
    origins: dict[str, WebStrandOrigin]


@dataclass(frozen=True)
class MemoryWebValidationReport:
    """Fail-closed validation result shared by init and doctor."""

    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.blockers


__all__ = [
    "MemoryLinkReference",
    "MemoryLinkRendering",
    "MemoryStrand",
    "MemoryWeb",
    "MemoryWebDiscovery",
    "MemoryWebDiscoveryIssue",
    "MemoryWebValidationReport",
    "ScopedMemoryWeb",
    "WebClosureMode",
    "WebRosterStyle",
    "WebScope",
    "WebSource",
    "WebStrandOrigin",
]
