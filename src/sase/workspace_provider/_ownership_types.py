"""Core types and path primitives for the workspace ownership contract.

Split out of :mod:`sase.workspace_provider.ownership`; import these names
from that module rather than depending on this one directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sase.workspace_provider.store import (
    LEGACY_PRIMARY_WORKSPACE_NUM,
    PRIMARY_WORKSPACE_NUM,
)

ProcessRunningProbe = Callable[[int], bool]

# Numbered checkouts below this are reserved (primary ``#0``, legacy ``#1``,
# and ``#2``-``#9``). Machine-owned leases come from the unified claim pool.
MACHINE_OWNED_MIN_WORKSPACE = 10


class MutationOrigin(StrEnum):
    """Who initiated a repository mutation."""

    USER = "user"
    MACHINE = "machine"


class AccessKind(StrEnum):
    """How an operation is allowed to touch a checkout or sidecar."""

    USER_DIRECTED = "user_directed"
    READ_ONLY_CANONICAL = "read_only_canonical"
    LEASED_OPERATIONAL = "leased_operational"
    PRIMARY_SIDECAR_SYNC = "primary_sidecar_sync"


class WorkspaceOwnershipError(RuntimeError):
    """Raised when a mutation is not allowed for the resolved checkout."""


@dataclass(frozen=True)
class OperationContext:
    """Resolved access rights for one project checkout or sidecar role."""

    project: str
    access_kind: AccessKind
    mutation_origin: MutationOrigin
    workspace_num: int
    checkout_dir: Path
    primary_checkout_dir: Path
    project_file: Path | None = None
    sidecar_role: str | None = None
    claim_pid: int | None = None
    claim_workflow: str | None = None

    @property
    def is_primary(self) -> bool:
        return self.workspace_num == PRIMARY_WORKSPACE_NUM

    @property
    def is_writable(self) -> bool:
        return self.access_kind is not AccessKind.READ_ONLY_CANONICAL


def normalize_workspace_num(workspace_num: int) -> int:
    """Map the legacy primary spelling ``#1`` onto canonical ``#0``."""

    if workspace_num == LEGACY_PRIMARY_WORKSPACE_NUM:
        return PRIMARY_WORKSPACE_NUM
    return workspace_num


def normalize_path(path: str | Path) -> Path:
    """Expand and resolve *path* without requiring it to exist."""

    return Path(path).expanduser().resolve(strict=False)


def path_is_within(path: Path, root: Path) -> bool:
    """Return whether *path* is *root* or lives beneath it."""

    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


__all__ = [
    "AccessKind",
    "MACHINE_OWNED_MIN_WORKSPACE",
    "MutationOrigin",
    "OperationContext",
    "ProcessRunningProbe",
    "WorkspaceOwnershipError",
    "normalize_path",
    "normalize_workspace_num",
    "path_is_within",
]
