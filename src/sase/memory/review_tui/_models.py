"""Small data models used by the memory review TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TargetSummary:
    target_path: str
    canonical_path: Path
    exists: bool
    diff: tuple[str, ...]
    error: str | None = None
