"""Immutable wire records for owner-sharded agents-sidecar v2 publication."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from sase.agents_sync.models import CommitRecord
from sase.core.agent_archive_facade import AgentArchiveCapabilities
from sase.core.agent_identity_facade import AgentOwnerIdentity

V2_SCHEMA_VERSION = 2

RunState = Literal[
    "active",
    "waiting",
    "completed",
    "failed",
    "stopped",
    "dismissed",
]
ContainerKind = Literal["family", "clan"]
RelationshipKind = Literal["parent", "workflow_parent", "retry", "wait"]


@dataclass(frozen=True, slots=True)
class V2ProjectIdentity:
    key: str
    name: str

    def to_json_dict(self) -> dict[str, str]:
        return {"key": self.key, "name": self.name}


@dataclass(frozen=True, slots=True)
class V2FileReference:
    path: str
    digest: str
    size_bytes: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "digest": self.digest,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class V2RunRecord:
    source_run_id: str
    local_name: str
    global_name: str
    state: RunState
    started_at: str | None = None
    finished_at: str | None = None
    dismissed_at: str | None = None
    metadata: tuple[tuple[str, Any], ...] = ()
    commits: tuple[CommitRecord, ...] = ()
    files: tuple[tuple[str, V2FileReference], ...] = ()
    capabilities: AgentArchiveCapabilities = field(
        default_factory=lambda: AgentArchiveCapabilities(
            historically_viewable=False,
            durably_revivable=False,
            restartable=False,
            missing_requirements=(
                "commits",
                "llm_provider",
                "loader_reconstructible_archive",
                "metadata",
                "model",
                "prompt",
                "reasoning_effort",
                "state",
            ),
        )
    )

    def to_json_dict(self) -> dict[str, object]:
        from sase.core.agent_archive_facade import capabilities_from_v2_run

        capabilities = capabilities_from_v2_run(
            dict(self.metadata), {kind for kind, _reference in self.files}
        )
        return {
            "source_run_id": self.source_run_id,
            "local_name": self.local_name,
            "global_name": self.global_name,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dismissed_at": self.dismissed_at,
            "metadata": dict(self.metadata),
            "commits": [commit.to_json_dict() for commit in self.commits],
            "files": {
                kind: reference.to_json_dict() for kind, reference in sorted(self.files)
            },
            "capabilities": capabilities.to_json_dict(),
        }


@dataclass(frozen=True, slots=True)
class V2RunMetadataPayload:
    owner: AgentOwnerIdentity
    project: V2ProjectIdentity
    source_run_id: str
    local_name: str
    global_name: str
    metadata: tuple[tuple[str, Any], ...] = ()
    schema_version: int = V2_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "owner": _owner_dict(self.owner),
            "project": self.project.to_json_dict(),
            "source_run_id": self.source_run_id,
            "local_name": self.local_name,
            "global_name": self.global_name,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class V2RunStatePayload:
    source_run_id: str
    state: RunState
    started_at: str | None = None
    finished_at: str | None = None
    dismissed_at: str | None = None
    schema_version: int = V2_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_run_id": self.source_run_id,
            "state": self.state,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dismissed_at": self.dismissed_at,
        }


@dataclass(frozen=True, slots=True)
class V2RunCommitsPayload:
    source_run_id: str
    commits: tuple[CommitRecord, ...] = ()
    schema_version: int = V2_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_run_id": self.source_run_id,
            "commits": [commit.to_json_dict() for commit in self.commits],
        }


@dataclass(frozen=True, slots=True)
class V2ContainerRecord:
    kind: ContainerKind
    global_name: str
    member_source_run_ids: tuple[str, ...]
    commits: tuple[CommitRecord, ...] = ()

    def to_json_dict(self, owner: AgentOwnerIdentity) -> dict[str, object]:
        return {
            **self.to_relationship_json_dict(owner),
            "commits": [commit.to_json_dict() for commit in self.commits],
        }

    def to_relationship_json_dict(self, owner: AgentOwnerIdentity) -> dict[str, object]:
        """Return the container fields owned by the Rust relationship schema."""

        return {
            "kind": self.kind,
            "global_name": self.global_name,
            "owner": _owner_dict(owner),
            "member_source_run_ids": list(self.member_source_run_ids),
        }


@dataclass(frozen=True, slots=True)
class V2RelationshipTarget:
    kind: Literal["source_run_id", "global_name"]
    source_run_id: str | None = None
    global_name: str | None = None
    owner: AgentOwnerIdentity | None = None

    def to_json_dict(self) -> dict[str, object]:
        if self.kind == "source_run_id":
            assert self.source_run_id is not None
            return {"kind": self.kind, "source_run_id": self.source_run_id}
        assert self.global_name is not None and self.owner is not None
        return {
            "kind": self.kind,
            "global_name": self.global_name,
            "owner": _owner_dict(self.owner),
        }


@dataclass(frozen=True, slots=True)
class V2RelationshipRecord:
    kind: RelationshipKind
    source_run_id: str
    target: V2RelationshipTarget
    required: bool

    def to_json_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "source_run_id": self.source_run_id,
            "target": self.target.to_json_dict(),
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class V2HoodSnapshot:
    owner: AgentOwnerIdentity
    project: V2ProjectIdentity
    local_hood: str
    global_hood: str
    structural_ancestors: tuple[str, ...] = ()
    runs: tuple[V2RunRecord, ...] = ()
    containers: tuple[V2ContainerRecord, ...] = ()
    relationships: tuple[V2RelationshipRecord, ...] = ()
    schema_version: int = V2_SCHEMA_VERSION

    def relationship_batch(self) -> dict[str, object]:
        owner = _owner_dict(self.owner)
        return {
            "schema_version": self.schema_version,
            "owner": owner,
            "runs": [
                {
                    "source_run_id": run.source_run_id,
                    "global_name": run.global_name,
                    "owner": owner,
                }
                for run in self.runs
            ],
            "containers": [
                container.to_relationship_json_dict(self.owner)
                for container in self.containers
            ],
            "relationships": [
                relationship.to_json_dict() for relationship in self.relationships
            ],
        }

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "owner": _owner_dict(self.owner),
            "project": self.project.to_json_dict(),
            "hood": {
                "local_name": self.local_hood,
                "global_name": self.global_hood,
            },
            "structural_ancestors": list(self.structural_ancestors),
            "runs": [run.to_json_dict() for run in self.runs],
            "containers": [
                container.to_json_dict(self.owner) for container in self.containers
            ],
            "relationships": [
                relationship.to_json_dict() for relationship in self.relationships
            ],
        }


@dataclass(frozen=True, slots=True)
class V2OwnerHoodEntry:
    digest: str
    files: tuple[str, ...]
    run_count: int
    family_count: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "files": list(self.files),
            "run_count": self.run_count,
            "family_count": self.family_count,
        }


@dataclass(frozen=True, slots=True)
class V2OwnerManifest:
    owner: AgentOwnerIdentity
    project: V2ProjectIdentity
    hoods: tuple[tuple[str, V2OwnerHoodEntry], ...] = ()
    schema_version: int = V2_SCHEMA_VERSION

    def by_hood(self) -> dict[str, V2OwnerHoodEntry]:
        return dict(self.hoods)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "owner": _owner_dict(self.owner),
            "project": self.project.to_json_dict(),
            "hoods": {hood: entry.to_json_dict() for hood, entry in sorted(self.hoods)},
        }


@dataclass(frozen=True, slots=True)
class V2PublicationCounts:
    hoods_published: int = 0
    hoods_refreshed: int = 0
    hoods_unchanged: int = 0
    families_published: int = 0
    runs_published: int = 0
    diagnostics: tuple[str, ...] = ()
    schema_version: int = V2_SCHEMA_VERSION

    @property
    def changed(self) -> int:
        return self.hoods_published + self.hoods_refreshed


def _owner_dict(owner: AgentOwnerIdentity) -> dict[str, str]:
    return {
        "username": owner.username,
        "machine_name": owner.machine_name,
    }


__all__ = [
    "ContainerKind",
    "RelationshipKind",
    "RunState",
    "V2ContainerRecord",
    "V2FileReference",
    "V2HoodSnapshot",
    "V2OwnerHoodEntry",
    "V2OwnerManifest",
    "V2ProjectIdentity",
    "V2PublicationCounts",
    "V2RelationshipRecord",
    "V2RelationshipTarget",
    "V2RunCommitsPayload",
    "V2RunMetadataPayload",
    "V2RunRecord",
    "V2RunStatePayload",
    "V2_SCHEMA_VERSION",
]
