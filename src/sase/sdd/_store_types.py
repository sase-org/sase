"""Shared data types and constants for SDD storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SddStorage = Literal["in_tree", "local", "separate_repo"]
SddConfiguredStorage = Literal["auto", "in_tree", "local", "separate_repo"]
SddPushAfterCommit = bool | Literal["async"]

SDD_STORAGE_AUTO: SddConfiguredStorage = "auto"
SDD_STORAGE_IN_TREE: SddStorage = "in_tree"
SDD_STORAGE_LOCAL: SddStorage = "local"
SDD_STORAGE_SEPARATE_REPO: SddStorage = "separate_repo"

SDD_STORE_RECORD_FILENAME = "sdd-store.json"

_CONFIGURED_STORAGE_VALUES: frozenset[str] = frozenset(
    {"auto", "in_tree", "local", "separate_repo"}
)
_STORAGE_VALUES: frozenset[str] = frozenset({"in_tree", "local", "separate_repo"})
_DISCOVERY_VALUES: frozenset[str] = frozenset({"found", "not_found"})


class SddMaterializationError(RuntimeError):
    """Raised when explicit separate-repo SDD storage cannot be materialized."""


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


@dataclass(frozen=True)
class SddStore:
    """Resolved SDD storage policy and concrete filesystem locations."""

    storage: SddStorage
    sdd_dir: Path
    repo_root: Path
    provider: str | None = None
    remote_url: str | None = None

    @property
    def is_in_tree(self) -> bool:
        return self.storage == SDD_STORAGE_IN_TREE
