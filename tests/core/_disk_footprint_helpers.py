"""Shared helpers for disk-footprint tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _ProjectInfo:
    project: str
    project_key: str
    root_dir: str
    cleanup_ttl_days: int
    primary_workspace_dir: str | None = None
    share_git_objects: bool = True


@dataclass(frozen=True)
class _Issue:
    project: str
    message: str


@dataclass(frozen=True)
class _Inventory:
    projects: tuple[_ProjectInfo, ...]
    issues: tuple[_Issue, ...] = ()


@dataclass(frozen=True)
class _ProcRuntimeRetentionStub:
    runtime_root: Path
    apply: bool
    scanned: int
    selected: int
    removed: int
    skipped: int
    errors: int
    reclaimable_bytes: int
    reclaimed_bytes: int
    capped: bool

    def describe(self) -> str:
        suffix = " (removal budget reached)" if self.capped else ""
        verb = "removed" if self.apply else "would remove"
        return (
            f"{verb} {self.removed if self.apply else self.selected} proc runtime "
            f"dir(s) under {self.runtime_root}; scanned={self.scanned}, "
            f"reclaimable={self.reclaimable_bytes}, reclaimed={self.reclaimed_bytes}"
            f"{suffix}"
        )


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
