"""Typed requests stored in the durable agent publication outbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

PUBLICATION_OUTBOX_SCHEMA_VERSION = 5

PublicationLogicalKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class AgentPublicationOutboxItem:
    """One idempotent primary-commit-to-sidecar agent-hood publication request."""

    project_key: str
    project: str
    local_agent: str
    global_agent: str
    primary_revision: str
    local_hood: str
    hood_digest: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    quarantined: bool = False
    quarantined_at: float | None = None
    terminal: bool = False
    terminal_reason: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    @property
    def logical_key(self) -> PublicationLogicalKey:
        return self.global_agent, self.primary_revision

    @property
    def id(self) -> str:
        payload = "\0".join(
            (
                self.project_key,
                self.global_agent,
                self.primary_revision,
                self.hood_digest,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "project_key": self.project_key,
            "project": self.project,
            "local_agent": self.local_agent,
            "global_agent": self.global_agent,
            "primary_revision": self.primary_revision,
            "local_hood": self.local_hood,
            "hood_digest": self.hood_digest,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "quarantined": self.quarantined,
            "quarantined_at": self.quarantined_at,
            "terminal": self.terminal,
            "terminal_reason": self.terminal_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def validate_publication_item(
    item: AgentPublicationOutboxItem,
    project_key: str,
) -> None:
    """Validate the identity and agent-hood fields of one request."""

    if item.project_key != project_key:
        raise RuntimeError("agents publication outbox project identity mismatch")
    if not all(
        (
            item.project_key,
            item.project,
            item.local_agent,
            item.global_agent,
            item.primary_revision,
            item.local_hood,
        )
    ):
        raise RuntimeError("agents publication outbox item is incomplete")


def publication_sort_key(
    item: AgentPublicationOutboxItem,
) -> tuple[float, str]:
    """Return the stable durable ordering key for one request."""

    return item.created_at, item.id


__all__ = [
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "AgentPublicationOutboxItem",
    "PublicationLogicalKey",
    "publication_sort_key",
    "validate_publication_item",
]
