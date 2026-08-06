"""Shared data types and constants for SDD storage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SddStorage = Literal["in_tree", "local", "separate_repo", "sidecar_repos"]

SDD_STORAGE_IN_TREE: SddStorage = "in_tree"
SDD_STORAGE_LOCAL: SddStorage = "local"
SDD_STORAGE_SEPARATE_REPO: SddStorage = "separate_repo"
SDD_STORAGE_SIDECAR_REPOS: SddStorage = "sidecar_repos"

SDD_STORE_RECORD_FILENAME = "sdd-store.json"

PLANS_SIDECAR_ROLE = "plans"
BEADS_SIDECAR_ROLE = "beads"
AGENTS_SIDECAR_ROLE = "agents"
RESERVED_SIDECAR_ROLES = frozenset(
    {PLANS_SIDECAR_ROLE, BEADS_SIDECAR_ROLE, AGENTS_SIDECAR_ROLE}
)

_STORAGE_VALUES: frozenset[str] = frozenset(
    {"in_tree", "local", "separate_repo", "sidecar_repos"}
)
_DISCOVERY_VALUES: frozenset[str] = frozenset({"found", "not_found"})


def document_sidecar_roles(
    roles: Iterable[str],
    *,
    include_plans: bool = False,
) -> tuple[str, ...]:
    """Return configured document roles in their original order.

    ``plans`` is reserved but is also a document corpus, so callers that need
    the complete corpus can opt into it explicitly. ``beads`` and ``agents``
    are never document roles.
    """

    return tuple(
        role
        for role in dict.fromkeys(roles)
        if role not in {BEADS_SIDECAR_ROLE, AGENTS_SIDECAR_ROLE}
        and (include_plans or role != PLANS_SIDECAR_ROLE)
    )


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
    sidecars: Mapping[str, SddSidecar] = field(default_factory=dict)

    @property
    def is_sidecar_storage(self) -> bool:
        return self.storage == SDD_STORAGE_SIDECAR_REPOS

    @property
    def plans(self) -> SddSidecar | None:
        """Return the reserved plans sidecar, when recorded."""

        return self.sidecar_for_kind(PLANS_SIDECAR_ROLE)

    @property
    def beads(self) -> SddSidecar | None:
        """Return the reserved beads sidecar, when separately recorded."""

        return self.sidecar_for_kind(BEADS_SIDECAR_ROLE)

    @property
    def has_split_beads(self) -> bool:
        """Return whether bead state has its own recorded sidecar."""

        return self.beads is not None

    def sidecar_for_kind(self, kind: str) -> SddSidecar | None:
        """Return the recorded sidecar for *kind*, if present."""

        return self.sidecars.get(kind)


@dataclass(frozen=True)
class SddStore:
    """Resolved SDD storage policy and concrete filesystem locations."""

    storage: SddStorage
    sdd_dir: Path
    repo_root: Path
    provider: str | None = None
    remote_url: str | None = None
    sidecar_dirs: Mapping[str, Path] = field(default_factory=dict)
    sidecar_remote_urls: Mapping[str, str] = field(default_factory=dict)
    beads_dir: Path | None = None
    beads_remote_url: str | None = None
    sidecar_role: str | None = None
    unresolved_sidecars: Mapping[str, str] = field(default_factory=dict)

    @property
    def is_in_tree(self) -> bool:
        return self.storage == SDD_STORAGE_IN_TREE

    @property
    def is_sidecar_storage(self) -> bool:
        return self.storage == SDD_STORAGE_SIDECAR_REPOS

    def kind_root(self, kind: str) -> Path:
        """Return the directory containing one logical SDD kind."""

        if self.is_sidecar_storage:
            if kind == BEADS_SIDECAR_ROLE:
                return self.beads_dir or self.sdd_dir / "beads"
            if kind == PLANS_SIDECAR_ROLE:
                return self.sdd_dir
            root = self.sidecar_dirs.get(kind)
            if root is None:
                if kind in self.unresolved_sidecars:
                    raise SddMaterializationError(self.unresolved_sidecars[kind])
                raise ValueError(f"sidecar SDD store has no {kind} root")
            return root
        return self.sdd_dir / kind

    def repo_root_for_kind(self, kind: str) -> Path:
        """Return the git repository root that owns one logical SDD kind."""

        if kind == BEADS_SIDECAR_ROLE and self.beads_dir is not None:
            return self.beads_dir
        if kind in {BEADS_SIDECAR_ROLE, PLANS_SIDECAR_ROLE}:
            return self.repo_root
        if not self.is_sidecar_storage:
            return self.repo_root
        root = self.sidecar_dirs.get(kind)
        if root is None:
            if kind in self.unresolved_sidecars:
                raise SddMaterializationError(self.unresolved_sidecars[kind])
            raise ValueError(f"sidecar SDD store has no {kind} repository")
        return root

    def remote_url_for_kind(self, kind: str) -> str | None:
        """Return the recorded remote URL for one logical SDD kind."""

        if kind == BEADS_SIDECAR_ROLE and self.beads_dir is not None:
            return self.beads_remote_url
        if kind in {BEADS_SIDECAR_ROLE, PLANS_SIDECAR_ROLE}:
            return self.remote_url
        if not self.is_sidecar_storage:
            return self.remote_url
        return self.sidecar_remote_urls.get(kind)

    def split_sidecar_roles(self) -> tuple[str, ...]:
        """Return every role backed by its own sidecar repository."""

        roles = [PLANS_SIDECAR_ROLE, *self.sidecar_dirs]
        if self.beads_dir is not None:
            roles.append(BEADS_SIDECAR_ROLE)
        return tuple(dict.fromkeys(roles))
