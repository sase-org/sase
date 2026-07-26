"""Shared data types and constants for SDD storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SddStorage = Literal["in_tree", "local", "separate_repo", "sidecar_repos"]

SDD_STORAGE_IN_TREE: SddStorage = "in_tree"
SDD_STORAGE_LOCAL: SddStorage = "local"
SDD_STORAGE_SEPARATE_REPO: SddStorage = "separate_repo"
SDD_STORAGE_SIDECAR_REPOS: SddStorage = "sidecar_repos"

SDD_STORE_RECORD_FILENAME = "sdd-store.json"

_STORAGE_VALUES: frozenset[str] = frozenset(
    {"in_tree", "local", "separate_repo", "sidecar_repos"}
)
_DISCOVERY_VALUES: frozenset[str] = frozenset({"found", "not_found"})


class SddMaterializationError(RuntimeError):
    """Raised when provider-owned separate-repo storage cannot be materialized."""


@dataclass(frozen=True)
class SddSidecar:
    """Repository identity for one side of a split SDD store."""

    repo: str
    remote_url: str


@dataclass(frozen=True)
class SddStoreRecord:
    """Persisted metadata for a materialized SDD store."""

    schema_version: int
    storage: SddStorage
    provider: str | None = None
    host: str | None = None
    repo: str | None = None
    remote_url: str | None = None
    discovery: str | None = None
    probed_at: str | None = None
    plans: SddSidecar | None = None
    research: SddSidecar | None = None

    @property
    def is_sidecar_storage(self) -> bool:
        return self.storage == SDD_STORAGE_SIDECAR_REPOS

    def sidecar_for_kind(self, kind: str) -> SddSidecar | None:
        if kind in {"plans", "beads"}:
            return self.plans
        if kind == "research":
            return self.research
        raise ValueError(f"unknown SDD kind: {kind}")


@dataclass(frozen=True)
class SddStore:
    """Resolved SDD storage policy and concrete filesystem locations."""

    storage: SddStorage
    sdd_dir: Path
    repo_root: Path
    provider: str | None = None
    remote_url: str | None = None
    research_dir: Path | None = None
    research_remote_url: str | None = None

    @property
    def is_in_tree(self) -> bool:
        return self.storage == SDD_STORAGE_IN_TREE

    @property
    def is_sidecar_storage(self) -> bool:
        return self.storage == SDD_STORAGE_SIDECAR_REPOS

    def kind_root(self, kind: str) -> Path:
        """Return the directory containing one logical SDD kind."""

        if self.is_sidecar_storage:
            if kind == "research":
                if self.research_dir is None:
                    raise ValueError("sidecar SDD store has no research root")
                return self.research_dir
            if kind == "beads":
                return self.sdd_dir / "beads"
            if kind == "plans":
                return self.sdd_dir
        if kind in {"beads", "plans", "research"}:
            return self.sdd_dir / kind
        raise ValueError(f"unknown SDD kind: {kind}")
