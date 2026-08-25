"""Shared types for provider-neutral commit finalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_DirtyRepoKind = Literal["main", "sibling", "external", "sdd"]

# Precedence when the same repo path is reached through more than one
# discovery source (e.g. a configured sibling that is also an SDD sidecar
# target): the more specific kind wins, since the machine auto-commit and
# prompt-rendering paths key off ``kind``.
DIRTY_REPO_KIND_PRIORITY: dict[str, int] = {
    "main": 0,
    "sdd": 1,
    "external": 2,
    "sibling": 3,
}


@dataclass(frozen=True)
class BeadStateSyncOutcome:
    """What the finalizer's bead-state safety net committed and published.

    ``publication_error`` holds the operator-facing diagnostic when the commit
    reached only the local checkout, so a finalizer-created bead commit cannot
    be reported as finalized while it is still invisible to everyone else.
    """

    committed: bool = False
    publication_error: str | None = None


@dataclass(frozen=True)
class BaselineRepo:
    name: str
    path: str
    kind: _DirtyRepoKind


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
