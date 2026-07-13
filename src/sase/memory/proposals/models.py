"""Data structures and errors for memory proposals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

MEMORY_PROPOSAL_SCHEMA_VERSION = 1
MEMORY_PROPOSAL_BODY_WARN_BYTES = 16 * 1024
MEMORY_PROPOSAL_BODY_MAX_BYTES = 256 * 1024

EvidenceKind = Literal["path", "chat", "url", "note"]
ReviewProposalEventType = Literal["approved", "approved_with_edits", "rejected"]
ProposalEventType = Literal["proposed", "approved", "approved_with_edits", "rejected"]
ProposalStatus = Literal["pending", "approved", "approved_with_edits", "rejected"]


class MemoryProposalError(ValueError):
    """Base class for memory-proposal validation errors."""


class MemoryProposalAuthorError(MemoryProposalError):
    """Raised when a proposal author cannot be attributed."""


class MemoryProposalEvidenceError(MemoryProposalError):
    """Raised when proposal evidence is missing or invalid."""


class MemoryProposalTargetError(MemoryProposalError):
    """Raised when a proposal target is not allowed."""


class MemoryProposalBodyError(MemoryProposalError):
    """Raised when a proposal body is missing or too large."""


class MemoryProposalLookupError(MemoryProposalError):
    """Raised when a proposal id or prefix cannot be resolved."""


class MemoryProposalReviewError(MemoryProposalError):
    """Raised when a proposal review action is not allowed."""


@dataclass(frozen=True)
class ProposalAuthor:
    """Attributable author for a memory proposal."""

    name: str
    source: str
    artifacts_dir: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    """Typed evidence attached to a memory proposal."""

    kind: EvidenceKind
    raw: str
    path: str | None = None
    resolved_path: str | None = None
    exists: bool | None = None
    byte_count: int | None = None
    sha256: str | None = None
    chat_id: str | None = None
    url: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class ProposalWarning:
    """Non-blocking warning recorded with a proposal event."""

    code: str
    message: str
    match: str | None = None


@dataclass(frozen=True)
class ProposalReviewer:
    """Human reviewer identity recorded with review events."""

    user: str
    hostname: str


@dataclass(frozen=True)
class MemoryProposalEvent:
    """Append-only event for the memory proposal ledger."""

    schema_version: int
    event_type: Literal["proposed"]
    proposal_id: str
    timestamp: str
    project: str
    cwd: str
    title: str
    target_path: str
    author_name: str
    author_source: str
    artifacts_dir: str | None
    body_path: str
    body_sha256: str
    body_byte_count: int
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[ProposalWarning, ...]


@dataclass(frozen=True)
class MemoryProposalReviewEvent:
    """Append-only review event for a memory proposal."""

    schema_version: int
    event_type: ReviewProposalEventType
    proposal_id: str
    timestamp: str
    project: str
    cwd: str
    reviewer_user: str
    reviewer_hostname: str
    target_path: str
    canonical_path: str | None
    reviewed_body_path: str | None
    body_sha256: str | None
    body_byte_count: int | None
    reason: str | None


MemoryProposalLedgerEvent = MemoryProposalEvent | MemoryProposalReviewEvent


@dataclass(frozen=True)
class MemoryProposalState:
    """Reduced current state for a memory proposal."""

    proposal_id: str
    status: ProposalStatus
    created_at: str
    updated_at: str
    project: str
    cwd: str
    title: str
    target_path: str
    author_name: str
    author_source: str
    artifacts_dir: str | None
    body_path: str
    body_sha256: str
    body_byte_count: int
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[ProposalWarning, ...]
    reviewed_at: str | None = None
    reviewer_user: str | None = None
    reviewer_hostname: str | None = None
    review_reason: str | None = None
    canonical_path: str | None = None
    reviewed_body_path: str | None = None


@dataclass(frozen=True)
class MemoryProposalWriteResult:
    """Result returned after appending a memory proposal."""

    event: MemoryProposalEvent
    state: MemoryProposalState
    ledger_path: Path
    lock_path: Path
    draft_path: Path


@dataclass(frozen=True)
class MemoryProposalReviewResult:
    """Result returned after appending a memory proposal review event."""

    event: MemoryProposalReviewEvent
    state: MemoryProposalState
    ledger_path: Path
    canonical_path: Path | None
    reviewed_path: Path | None
    warnings: tuple[ProposalWarning, ...]
