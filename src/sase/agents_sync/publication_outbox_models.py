"""Typed requests stored in the durable agent publication outbox."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

PUBLICATION_OUTBOX_SCHEMA_VERSION = 7
PUBLICATION_SCOPE_LINKED = "linked"
PUBLICATION_SCOPE_REVISION = "revision"
_PUBLICATION_SCOPES = frozenset({PUBLICATION_SCOPE_LINKED, PUBLICATION_SCOPE_REVISION})

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
    scope: str = PUBLICATION_SCOPE_REVISION
    requested_revision: str | None = None
    commit_cwd: str | None = None
    artifacts_dir: str | None = None
    run_id: str | None = None
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
    def original_revision(self) -> str:
        """Return the revision the row requested before any stale repair."""

        return self.requested_revision or self.primary_revision

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
            "scope": self.scope,
            "requested_revision": self.requested_revision,
            "commit_cwd": self.commit_cwd,
            "artifacts_dir": self.artifacts_dir,
            "run_id": self.run_id,
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
    if item.scope not in _PUBLICATION_SCOPES:
        raise RuntimeError(
            f"agents publication outbox scope must be "
            f"{PUBLICATION_SCOPE_REVISION} or {PUBLICATION_SCOPE_LINKED}"
        )
    if item.requested_revision is not None and not item.requested_revision:
        raise RuntimeError(
            "agents publication outbox requested revision must be "
            "a non-empty string or null"
        )
    for field_name, value in (
        ("commit_cwd", item.commit_cwd),
        ("artifacts_dir", item.artifacts_dir),
        ("run_id", item.run_id),
    ):
        if value is not None and not value:
            raise RuntimeError(
                f"agents publication outbox {field_name} must be "
                "a non-empty string or null"
            )


def publication_sort_key(
    item: AgentPublicationOutboxItem,
) -> tuple[float, str]:
    """Return the stable durable ordering key for one request."""

    return item.created_at, item.id


__all__ = [
    "PUBLICATION_OUTBOX_SCHEMA_VERSION",
    "PUBLICATION_SCOPE_LINKED",
    "PUBLICATION_SCOPE_REVISION",
    "AgentPublicationOutboxItem",
    "PublicationLogicalKey",
    "publication_sort_key",
    "validate_publication_item",
]
