"""Typed requests stored in the durable sidecar publication outbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Literal

PUBLICATION_OUTBOX_SCHEMA_VERSION = 4

PublicationKind = Literal[
    "agent_hood",
    "bead_pages",
    "plan_header",
    "sidecar_push",
]
PublicationLogicalKey = tuple[str, str]
PUBLICATION_KIND_RANK: dict[PublicationKind, int] = {
    "agent_hood": 0,
    "bead_pages": 1,
    "plan_header": 2,
    "sidecar_push": 3,
}


@dataclass(frozen=True, slots=True)
class AgentPublicationOutboxItem:
    """One idempotent sidecar publication request.

    The historical class name remains part of the public API. Schema v4 makes
    the record typed while preserving the v1-v3 agent-hood fields and logical
    key exactly. Non-agent request constructors below keep their irrelevant
    legacy fields empty.
    """

    project_key: str
    project: str
    local_agent: str = ""
    global_agent: str = ""
    primary_revision: str = ""
    local_hood: str = ""
    hood_digest: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    quarantined: bool = False
    quarantined_at: float | None = None
    terminal: bool = False
    terminal_reason: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    kind: PublicationKind = "agent_hood"
    bead_id: str = ""
    lineage_root: str = ""
    plan_ref: str = ""
    commit_message: str = ""
    sidecar_kind: str = ""

    @property
    def logical_key(self) -> PublicationLogicalKey:
        if self.kind == "agent_hood":
            return self.global_agent, self.primary_revision
        if self.kind == "bead_pages":
            return self.lineage_root, self.primary_revision
        if self.kind == "plan_header":
            return self.plan_ref, self.primary_revision
        return self.sidecar_kind, self.project_key

    @property
    def ordering_rank(self) -> int:
        """Stable dependency order used by every queue drainer."""

        return PUBLICATION_KIND_RANK[self.kind]

    @property
    def id(self) -> str:
        payload = "\0".join(
            (
                self.project_key,
                self.kind,
                *self.logical_key,
                self.hood_digest if self.kind == "agent_hood" else "",
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "kind": self.kind,
            "rank": self.ordering_rank,
            "project_key": self.project_key,
            "project": self.project,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "quarantined": self.quarantined,
            "quarantined_at": self.quarantined_at,
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.kind == "agent_hood":
            result.update(
                {
                    "local_agent": self.local_agent,
                    "global_agent": self.global_agent,
                    "primary_revision": self.primary_revision,
                    "local_hood": self.local_hood,
                    "hood_digest": self.hood_digest,
                }
            )
        elif self.kind == "bead_pages":
            result.update(
                {
                    "bead_id": self.bead_id,
                    "lineage_root": self.lineage_root,
                    "primary_revision": self.primary_revision,
                }
            )
        elif self.kind == "plan_header":
            result.update(
                {
                    "plan_ref": self.plan_ref,
                    "primary_revision": self.primary_revision,
                    "commit_message": self.commit_message,
                }
            )
        else:
            result["sidecar_kind"] = self.sidecar_kind
        return result


# A clearer schema-v4 name for new callers. Keep the old name above because it
# is imported by agents sync, doctor, and provenance consumers.
SidecarPublicationRequest = AgentPublicationOutboxItem


def bead_pages_publication_request(
    *,
    project_key: str,
    project: str,
    bead_id: str,
    lineage_root: str,
    primary_revision: str = "",
) -> SidecarPublicationRequest:
    """Build one workspace-independent bead-lineage publication request."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="bead_pages",
        bead_id=bead_id,
        lineage_root=lineage_root,
        primary_revision=primary_revision,
    )


def plan_header_publication_request(
    *,
    project_key: str,
    project: str,
    plan_ref: str,
    primary_revision: str,
    commit_message: str,
) -> SidecarPublicationRequest:
    """Build one workspace-independent committed-plan refresh request."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="plan_header",
        plan_ref=plan_ref,
        primary_revision=primary_revision,
        commit_message=commit_message,
    )


def sidecar_push_publication_request(
    *,
    project_key: str,
    project: str,
    sidecar_kind: str,
) -> SidecarPublicationRequest:
    """Build one coalescing request to push a project's sidecar repository."""

    return SidecarPublicationRequest(
        project_key=project_key,
        project=project,
        kind="sidecar_push",
        sidecar_kind=sidecar_kind,
    )


def validate_publication_item(
    item: SidecarPublicationRequest,
    project_key: str,
) -> None:
    """Validate the identity and kind-specific fields of one request."""

    if item.project_key != project_key:
        raise RuntimeError("agents publication outbox project identity mismatch")
    if not item.project_key or not item.project:
        raise RuntimeError("agents publication outbox item is incomplete")
    required: tuple[str, ...]
    if item.kind == "agent_hood":
        required = (
            item.local_agent,
            item.global_agent,
            item.primary_revision,
            item.local_hood,
        )
    elif item.kind == "bead_pages":
        required = (item.bead_id, item.lineage_root)
    elif item.kind == "plan_header":
        required = (item.plan_ref, item.primary_revision, item.commit_message)
    else:
        required = (item.sidecar_kind,)
    if not all(required):
        raise RuntimeError("agents publication outbox item is incomplete")


def publication_sort_key(
    item: SidecarPublicationRequest,
) -> tuple[int, float, str]:
    """Return the stable durable ordering key for one request."""

    return item.ordering_rank, item.created_at, item.id


__all__ = [
    "PUBLICATION_KIND_RANK",
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "AgentPublicationOutboxItem",
    "PublicationKind",
    "PublicationLogicalKey",
    "SidecarPublicationRequest",
    "bead_pages_publication_request",
    "plan_header_publication_request",
    "publication_sort_key",
    "sidecar_push_publication_request",
    "validate_publication_item",
]
