"""Data models for SASE's frontend-neutral repository inventory."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

RepoKind = Literal["primary", "sidecar", "linked", "external"]


@dataclass(frozen=True)
class RepoCloneRecord:
    """One repository's path and presence in a registered workspace."""

    workspace_num: int
    path: str
    exists: bool

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe representation of this clone."""

        return asdict(self)


@dataclass(frozen=True)
class RepoRecord:
    """One primary, sidecar, linked, or external repository known by SASE."""

    name: str
    kind: RepoKind
    project: str
    project_key: str
    path: str
    exists: bool
    auto_clone: bool
    description: str | None
    source: str
    env_name: str | None
    slug: str | None = None
    remote_url: str | None = None
    sdd_storage: str | None = None
    clones: tuple[RepoCloneRecord, ...] = ()
    auto_sync: bool = False

    def clone_for_workspace(self, workspace_num: int) -> RepoCloneRecord | None:
        """Return this repo's clone record for *workspace_num*, if registered."""

        return next(
            (clone for clone in self.clones if clone.workspace_num == workspace_num),
            None,
        )

    def to_json_dict(self, *, workspace_num: int | None = None) -> dict[str, object]:
        """Return a stable JSON-safe representation of this record."""

        selected = (
            self.clone_for_workspace(workspace_num)
            if workspace_num is not None
            else None
        )
        return {
            "name": self.name,
            "kind": self.kind,
            "project": self.project,
            "project_key": self.project_key,
            "path": selected.path if selected is not None else self.path,
            "exists": selected.exists if selected is not None else self.exists,
            "auto_clone": self.auto_clone,
            "auto_sync": self.auto_sync,
            "description": self.description,
            "source": self.source,
            "env_name": self.env_name,
            "slug": self.slug,
            "remote_url": self.remote_url,
            "sdd_storage": self.sdd_storage,
            "clones": [clone.to_json_dict() for clone in self.clones],
        }


@dataclass(frozen=True)
class RepoInventoryIssue:
    """A non-fatal problem isolated to one host project."""

    project: str
    message: str

    def to_json_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RepoInventory:
    """Repository records plus non-fatal per-project issues."""

    records: tuple[RepoRecord, ...]
    issues: tuple[RepoInventoryIssue, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "repos": [record.to_json_dict() for record in self.records],
            "issues": [issue.to_json_dict() for issue in self.issues],
        }


class RepoInventoryProjectNotFoundError(ValueError):
    """Raised when an explicit project filter matches no inventory host."""
