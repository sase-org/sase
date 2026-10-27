"""Shared wait_checks chop types.

Public dataclasses needed by more than one wait_checks implementation
module. Each symbol is imported by both the run and terminal modules,
so the shared home must be an already-private module with public names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WaitingMarker:
    project_name: str
    ready_path: Path
    waiting_path: Path


@dataclass(frozen=True)
class TerminalBlocker:
    dependency: str
    artifact_dir: str
    outcome: str


@dataclass(frozen=True)
class StrandedBeadWaiter:
    """One waiter currently blocked on an unclosed bead."""

    name: str
    artifact_dir: str


__all__ = [
    "StrandedBeadWaiter",
    "TerminalBlocker",
    "WaitingMarker",
]
