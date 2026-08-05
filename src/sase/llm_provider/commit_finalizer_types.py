"""Shared types for provider-neutral commit finalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_DEFAULT_ENABLED = True
_DEFAULT_MAX_PASSES = 2

_FinalizerStatus = Literal["skipped", "clean", "finalized", "failed"]
_DirtyRepoKind = Literal["main", "sibling", "external", "sdd"]


class CommitFinalizerError(Exception):
    """Raised when the commit finalizer cannot prove the workspace is clean."""


@dataclass(frozen=True)
class CommitFinalizerConfig:
    enabled: bool = _DEFAULT_ENABLED
    max_passes: int = _DEFAULT_MAX_PASSES


@dataclass(frozen=True)
class CommitFinalizerResult:
    status: _FinalizerStatus
    reason: str
    project_dir: str | None
    passes: int
    changed_files: list[str]
    error: str | None = None
    no_progress_passes: int = 0


@dataclass(frozen=True)
class DirtyRepo:
    name: str
    path: str
    changed_files: tuple[str, ...]
    kind: _DirtyRepoKind


@dataclass(frozen=True)
class DirtyState:
    project_dir: str
    repos: tuple[DirtyRepo, ...]
    details: str

    @property
    def is_clean(self) -> bool:
        return not self.repos


@dataclass(frozen=True)
class SiblingTarget:
    name: str
    workspace_dir: str
