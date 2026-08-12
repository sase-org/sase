"""Typed requests stored in the durable Referenced By outbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

REFERENCED_BY_OUTBOX_SCHEMA_VERSION = 1

ReferencedByLogicalKey = tuple[str, str, str, str]


@dataclass(frozen=True, slots=True)
class ReferencedByOutboxItem:
    """One idempotent prompt-publication-to-artifact back-reference request."""

    project_key: str
    project: str
    global_agent: str
    agent_url: str | None
    primary_revision: str
    sidecar_role: str
    provider: str
    artifact_id: str
    repo_relpath: str
    identity_value: str | None
    canonical_ref: str
    destination: str | None
    uses: int
    published_date: str
    attempts: int = 0
    last_error: str | None = None
    quarantined: bool = False
    quarantined_at: float | None = None
    terminal: bool = False
    terminal_reason: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def logical_key(self) -> ReferencedByLogicalKey:
        return (
            self.global_agent,
            self.primary_revision,
            self.sidecar_role,
            self.artifact_id,
        )

    @property
    def id(self) -> str:
        payload = "\0".join((self.project_key, *self.logical_key))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_key": self.project_key,
            "project": self.project,
            "global_agent": self.global_agent,
            "agent_url": self.agent_url,
            "primary_revision": self.primary_revision,
            "sidecar_role": self.sidecar_role,
            "provider": self.provider,
            "artifact_id": self.artifact_id,
            "repo_relpath": self.repo_relpath,
            "identity_value": self.identity_value,
            "canonical_ref": self.canonical_ref,
            "destination": self.destination,
            "uses": self.uses,
            "published_date": self.published_date,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "quarantined": self.quarantined,
            "quarantined_at": self.quarantined_at,
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def validate_referenced_by_item(
    item: ReferencedByOutboxItem,
    project_key: str,
) -> None:
    """Validate the identity fields of one back-reference request."""

    if item.project_key != project_key:
        raise RuntimeError("referenced-by outbox project identity mismatch")
    if not all(
        (
            item.project_key,
            item.project,
            item.global_agent,
            item.primary_revision,
            item.sidecar_role,
            item.provider,
            item.artifact_id,
            item.repo_relpath,
            item.canonical_ref,
            item.published_date,
        )
    ):
        raise RuntimeError("referenced-by outbox item is incomplete")
    if item.uses < 1:
        raise RuntimeError("referenced-by outbox item uses must be positive")


def referenced_by_sort_key(
    item: ReferencedByOutboxItem,
) -> tuple[float, str]:
    """Return the stable durable ordering key for one request."""

    return item.created_at, item.id


__all__ = [
    "REFERENCED_BY_OUTBOX_SCHEMA_VERSION",
    "ReferencedByLogicalKey",
    "ReferencedByOutboxItem",
    "referenced_by_sort_key",
    "validate_referenced_by_item",
]
