"""Proposal storage for ``sase memory write``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.memory.read_log import (
    AgentIdentity,
    AgentIdentityError,
    require_agent_identity,
)

MEMORY_PROPOSAL_SCHEMA_VERSION = 1
MEMORY_PROPOSAL_BODY_WARN_BYTES = 16 * 1024
MEMORY_PROPOSAL_BODY_MAX_BYTES = 256 * 1024

EvidenceKind = Literal["path", "chat", "url", "note"]
ReviewProposalEventType = Literal["approved", "approved_with_edits", "rejected"]
ProposalEventType = Literal["proposed", "approved", "approved_with_edits", "rejected"]
ProposalStatus = Literal["pending", "approved", "approved_with_edits", "rejected"]

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_PROPOSAL_ID_RE = re.compile(r"^mem-\d{8}-\d{6}-[0-9a-f]{8}$")
_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(r"\bignore (?:all )?(?:previous|prior) instructions\b", re.I),
    ),
    (
        "disregard_instructions",
        re.compile(r"\bdisregard (?:all )?(?:previous|prior)? ?instructions\b", re.I),
    ),
    ("system_prompt", re.compile(r"\bsystem prompt\b", re.I)),
    ("developer_message", re.compile(r"\bdeveloper message\b", re.I)),
    ("prompt_injection", re.compile(r"\bprompt injection\b", re.I)),
)


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


class _MemoryProposalLookupError(MemoryProposalError):
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
    keywords: tuple[str, ...]
    author_name: str
    author_source: str
    artifacts_dir: str | None
    body_path: str
    body_sha256: str
    body_byte_count: int
    evidence: tuple[EvidenceRecord, ...]
    warnings: tuple[ProposalWarning, ...]


@dataclass(frozen=True)
class _MemoryProposalReviewEvent:
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


MemoryProposalLedgerEvent = MemoryProposalEvent | _MemoryProposalReviewEvent


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
    keywords: tuple[str, ...]
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

    event: _MemoryProposalReviewEvent
    state: MemoryProposalState
    ledger_path: Path
    canonical_path: Path | None
    reviewed_path: Path | None
    warnings: tuple[ProposalWarning, ...]


def memory_proposal_ledger_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped memory-proposal JSONL ledger path."""
    project_name = project or project_memory_name(cwd or Path.cwd())
    return Path.home() / ".sase" / "projects" / project_name / "memory_proposals.jsonl"


def memory_proposal_lock_path(
    project: str | None = None,
    *,
    cwd: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Return the lock companion for a memory-proposal ledger path."""
    path = ledger_path or memory_proposal_ledger_path(project, cwd=cwd)
    return path.with_suffix(".lock")


def require_proposal_author(
    *,
    manual_author: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProposalAuthor:
    """Return the current proposal author or raise a write-specific error."""
    if manual_author is not None:
        name = manual_author.strip()
        if not name:
            raise MemoryProposalAuthorError("manual proposal author must not be empty")
        return ProposalAuthor(name=name, source="manual", artifacts_dir=None)

    try:
        identity = require_agent_identity(env)
    except AgentIdentityError as exc:
        raise MemoryProposalAuthorError(
            "memory writes require agent attribution; set SASE_AGENT_NAME, "
            "SASE_AGENT, provide SASE_ARTIFACTS_DIR/agent_meta.json with a name, "
            "or pass --manual-author for tests and demos"
        ) from exc
    return proposal_author_from_agent(identity)


def proposal_author_from_agent(agent: AgentIdentity) -> ProposalAuthor:
    """Convert a read-log agent identity to a proposal author."""
    return ProposalAuthor(
        name=agent.name,
        source=agent.source,
        artifacts_dir=agent.artifacts_dir,
    )


def require_proposal_reviewer(
    *, env: Mapping[str, str] | None = None
) -> ProposalReviewer:
    """Return the current human reviewer or raise for agent environments."""
    environment = os.environ if env is None else env
    if environment.get("SASE_AGENT_NAME") or environment.get("SASE_AGENT"):
        raise MemoryProposalReviewError(
            "memory proposal review must be performed by a human reviewer; "
            "agents cannot approve or reject proposals"
        )

    user = getpass.getuser().strip() or "unknown"
    hostname = socket.gethostname().strip() or "unknown"
    return ProposalReviewer(user=user, hostname=hostname)


def validate_memory_proposal_target(
    target: str | None = None, *, slug: str | None = None
) -> str:
    """Validate a one-level ``long/<slug>.md`` proposal target path."""
    if target is not None and slug is not None:
        raise MemoryProposalTargetError("pass either --target or --slug, not both")
    if target is None and slug is None:
        raise MemoryProposalTargetError("memory proposal target is required")

    if slug is not None:
        normalized_slug = slug.strip()
        if not _SLUG_RE.fullmatch(normalized_slug):
            raise MemoryProposalTargetError(
                "memory proposal slug must match [a-z0-9][a-z0-9_-]*"
            )
        return f"long/{normalized_slug}.md"

    raw_target = (target or "").strip()
    path = Path(raw_target)
    if not raw_target:
        raise MemoryProposalTargetError("memory proposal target must not be empty")
    if path.is_absolute():
        raise MemoryProposalTargetError("memory proposal target must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise MemoryProposalTargetError(
            "memory proposal target must not contain traversal"
        )
    if len(path.parts) != 2 or path.parts[0] != "long":
        raise MemoryProposalTargetError(
            "memory proposal target must be a one-level long/<slug>.md path"
        )
    if path.suffix != ".md":
        raise MemoryProposalTargetError("memory proposal target must end with .md")
    slug_value = path.stem
    if not _SLUG_RE.fullmatch(slug_value):
        raise MemoryProposalTargetError(
            "memory proposal target slug must match [a-z0-9][a-z0-9_-]*"
        )
    return path.as_posix()


def normalize_proposal_keywords(keywords: Iterable[str]) -> tuple[str, ...]:
    """Normalize keywords while preserving first-seen order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        value = keyword.strip()
        if not value:
            continue
        if value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return tuple(normalized)


def parse_memory_proposal_evidence(
    evidence_values: Iterable[str], *, cwd: Path | None = None
) -> tuple[EvidenceRecord, ...]:
    """Parse raw evidence strings into typed evidence records."""
    root = (cwd or Path.cwd()).resolve(strict=False)
    records = tuple(_parse_one_evidence(value, cwd=root) for value in evidence_values)
    if not records:
        raise MemoryProposalEvidenceError("memory proposals require evidence")
    if all(record.kind == "note" for record in records):
        raise MemoryProposalEvidenceError(
            "memory proposals require at least one non-note evidence item"
        )
    return records


def build_memory_proposal_warnings(
    body: str, *, byte_count: int, allow_large: bool
) -> tuple[ProposalWarning, ...]:
    """Build non-blocking proposal warnings."""
    warnings: list[ProposalWarning] = []
    if byte_count > MEMORY_PROPOSAL_BODY_WARN_BYTES and not allow_large:
        warnings.append(
            ProposalWarning(
                code="large_body",
                message="proposal body is larger than 16 KiB",
            )
        )

    for code, pattern in _PROMPT_INJECTION_PATTERNS:
        for match in pattern.finditer(body):
            warnings.append(
                ProposalWarning(
                    code=f"prompt_injection.{code}",
                    message="proposal body contains prompt-injection-like text",
                    match=match.group(0),
                )
            )
    return tuple(warnings)


def create_memory_proposal(
    *,
    title: str,
    body: str,
    evidence_values: Iterable[str],
    target: str | None = None,
    slug: str | None = None,
    keywords: Iterable[str] = (),
    author: ProposalAuthor | None = None,
    manual_author: str | None = None,
    allow_large: bool = False,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    proposal_id: str | None = None,
    ledger_path: Path | None = None,
) -> MemoryProposalWriteResult:
    """Create, persist, and reduce a pending memory proposal."""
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    normalized_title = _normalize_title(title)
    target_path = validate_memory_proposal_target(target, slug=slug)
    evidence = parse_memory_proposal_evidence(evidence_values, cwd=cwd_path)
    normalized_keywords = normalize_proposal_keywords(keywords)
    proposal_author = author or require_proposal_author(manual_author=manual_author)
    body_bytes = _validate_body(body)
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    final_proposal_id = proposal_id or generate_memory_proposal_id(now=now)
    if not _PROPOSAL_ID_RE.fullmatch(final_proposal_id):
        raise MemoryProposalError(
            "memory proposal id must match mem-YYYYMMDD-HHMMSS-<8hex>"
        )
    warnings = build_memory_proposal_warnings(
        body,
        byte_count=len(body_bytes),
        allow_large=allow_large,
    )

    final_ledger_path = ledger_path or memory_proposal_ledger_path(project_name)
    lock_path = memory_proposal_lock_path(ledger_path=final_ledger_path)
    draft_path = (
        final_ledger_path.parent / "memory_proposals" / final_proposal_id / "draft.md"
    )
    event = MemoryProposalEvent(
        schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
        event_type="proposed",
        proposal_id=final_proposal_id,
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        title=normalized_title,
        target_path=target_path,
        keywords=normalized_keywords,
        author_name=proposal_author.name,
        author_source=proposal_author.source,
        artifacts_dir=proposal_author.artifacts_dir,
        body_path=str(draft_path),
        body_sha256=body_sha256,
        body_byte_count=len(body_bytes),
        evidence=evidence,
        warnings=warnings,
    )

    _append_memory_proposal_event(event, body=body, ledger_path=final_ledger_path)
    state = reduce_memory_proposal_events((event,))[0]
    return MemoryProposalWriteResult(
        event=event,
        state=state,
        ledger_path=final_ledger_path,
        lock_path=lock_path,
        draft_path=draft_path,
    )


def resolve_memory_proposal_id(
    proposal_ref: str, states: Iterable[MemoryProposalState]
) -> MemoryProposalState:
    """Resolve an exact proposal id or unambiguous id prefix."""
    ref = proposal_ref.strip()
    if not ref:
        raise _MemoryProposalLookupError("memory proposal id must not be empty")

    states_tuple = tuple(states)
    for state in states_tuple:
        if state.proposal_id == ref:
            return state

    matches = tuple(
        state for state in states_tuple if state.proposal_id.startswith(ref)
    )
    if not matches:
        raise _MemoryProposalLookupError(f"unknown memory proposal id: {ref}")
    if len(matches) > 1:
        matching_ids = ", ".join(state.proposal_id for state in matches)
        raise _MemoryProposalLookupError(
            f"ambiguous memory proposal id prefix: {ref} ({matching_ids})"
        )
    return matches[0]


def reject_memory_proposal(
    proposal_ref: str,
    *,
    reason: str,
    reviewer: ProposalReviewer | None = None,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    ledger_path: Path | None = None,
) -> MemoryProposalReviewResult:
    """Reject a pending memory proposal and append a review event."""
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise MemoryProposalReviewError("memory proposal rejection reason is required")
    proposal_reviewer = reviewer or require_proposal_reviewer()
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    final_ledger_path = ledger_path or memory_proposal_ledger_path(
        project, cwd=cwd_path
    )
    event: _MemoryProposalReviewEvent
    state: MemoryProposalState
    with locked_file(
        memory_proposal_lock_path(ledger_path=final_ledger_path), fcntl.LOCK_EX
    ):
        events = _read_memory_proposal_events_unlocked(final_ledger_path)
        state = resolve_memory_proposal_id(
            proposal_ref, reduce_memory_proposal_events(events)
        )
        _ensure_pending_review(state)
        event = _MemoryProposalReviewEvent(
            schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
            event_type="rejected",
            proposal_id=state.proposal_id,
            timestamp=_event_timestamp(now or datetime.now(tz=UTC)),
            project=state.project,
            cwd=str(cwd_path),
            reviewer_user=proposal_reviewer.user,
            reviewer_hostname=proposal_reviewer.hostname,
            target_path=state.target_path,
            canonical_path=None,
            reviewed_body_path=None,
            body_sha256=None,
            body_byte_count=None,
            reason=normalized_reason,
        )
        _append_event_to_ledger_unlocked(event, final_ledger_path)
        state = resolve_memory_proposal_id(
            state.proposal_id, reduce_memory_proposal_events((*events, event))
        )

    return MemoryProposalReviewResult(
        event=event,
        state=state,
        ledger_path=final_ledger_path,
        canonical_path=None,
        reviewed_path=None,
        warnings=(),
    )


def approve_memory_proposal(
    proposal_ref: str,
    *,
    target: str | None = None,
    edited_file: Path | str | None = None,
    reviewer: ProposalReviewer | None = None,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    ledger_path: Path | None = None,
) -> MemoryProposalReviewResult:
    """Approve a pending proposal and create its canonical long-memory file."""
    proposal_reviewer = reviewer or require_proposal_reviewer()
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    final_ledger_path = ledger_path or memory_proposal_ledger_path(
        project, cwd=cwd_path
    )
    event: _MemoryProposalReviewEvent
    state: MemoryProposalState
    canonical_path: Path
    reviewed_path: Path | None
    with locked_file(
        memory_proposal_lock_path(ledger_path=final_ledger_path), fcntl.LOCK_EX
    ):
        events = _read_memory_proposal_events_unlocked(final_ledger_path)
        state = resolve_memory_proposal_id(
            proposal_ref, reduce_memory_proposal_events(events)
        )
        _ensure_pending_review(state)
        target_path = (
            validate_memory_proposal_target(target)
            if target is not None
            else state.target_path
        )
        canonical_path = cwd_path / "memory" / target_path
        body, reviewed_path = _approval_body_and_reviewed_path(
            state,
            edited_file=edited_file,
        )
        body_bytes = _validate_body(body)
        body_sha256 = hashlib.sha256(body_bytes).hexdigest()
        canonical_body = _canonical_memory_content(
            proposal_id=state.proposal_id,
            keywords=state.keywords,
            body=body,
        )
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with canonical_path.open("x", encoding="utf-8") as output_file:
                output_file.write(canonical_body)
        except FileExistsError as exc:
            raise MemoryProposalTargetError(
                f"memory proposal target already exists: {target_path}"
            ) from exc

        event = _MemoryProposalReviewEvent(
            schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
            event_type="approved_with_edits" if edited_file is not None else "approved",
            proposal_id=state.proposal_id,
            timestamp=_event_timestamp(now or datetime.now(tz=UTC)),
            project=state.project,
            cwd=str(cwd_path),
            reviewer_user=proposal_reviewer.user,
            reviewer_hostname=proposal_reviewer.hostname,
            target_path=target_path,
            canonical_path=str(canonical_path),
            reviewed_body_path=str(reviewed_path)
            if reviewed_path is not None
            else None,
            body_sha256=body_sha256,
            body_byte_count=len(body_bytes),
            reason=None,
        )
        _append_event_to_ledger_unlocked(event, final_ledger_path)
        state = resolve_memory_proposal_id(
            state.proposal_id, reduce_memory_proposal_events((*events, event))
        )

    warnings = _approval_reachability_warnings(
        state,
        canonical_path=canonical_path,
        cwd=cwd_path,
    )
    return MemoryProposalReviewResult(
        event=event,
        state=state,
        ledger_path=final_ledger_path,
        canonical_path=canonical_path,
        reviewed_path=reviewed_path,
        warnings=warnings,
    )


def prepare_memory_proposal_edit(
    proposal_ref: str,
    *,
    reviewer: ProposalReviewer | None = None,
    project: str | None = None,
    cwd: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Copy a proposal draft to ``reviewed.md`` before opening an editor."""
    if reviewer is None:
        require_proposal_reviewer()
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    final_ledger_path = ledger_path or memory_proposal_ledger_path(
        project, cwd=cwd_path
    )
    state = resolve_memory_proposal_id(
        proposal_ref, read_memory_proposals(ledger_path=final_ledger_path)
    )
    _ensure_pending_review(state)
    body = _read_required_text(Path(state.body_path), label="proposal draft")
    reviewed_path = _reviewed_body_path(state)
    reviewed_path.parent.mkdir(parents=True, exist_ok=True)
    reviewed_path.write_text(body, encoding="utf-8")
    return reviewed_path


def generate_memory_proposal_id(*, now: datetime | None = None) -> str:
    """Generate a proposal id shaped like ``mem-YYYYMMDD-HHMMSS-<8hex>``."""
    timestamp = now or datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    stamp = timestamp.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"mem-{stamp}-{uuid4().hex[:8]}"


def read_memory_proposal_events(
    *,
    project: str | None = None,
    ledger_path: Path | None = None,
) -> tuple[MemoryProposalLedgerEvent, ...]:
    """Read proposal ledger events, skipping malformed JSONL rows."""
    path = ledger_path or memory_proposal_ledger_path(project)
    with locked_file(memory_proposal_lock_path(ledger_path=path), fcntl.LOCK_SH):
        return _read_memory_proposal_events_unlocked(path)


def _read_memory_proposal_events_unlocked(
    path: Path,
) -> tuple[MemoryProposalLedgerEvent, ...]:
    if not path.exists():
        return ()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()

    events: list[MemoryProposalLedgerEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, Mapping):
            continue
        event = _proposal_event_from_mapping(data)
        if event is not None:
            events.append(event)
    return tuple(events)


def read_memory_proposals(
    *,
    project: str | None = None,
    ledger_path: Path | None = None,
) -> tuple[MemoryProposalState, ...]:
    """Read and reduce proposal states from the ledger."""
    return reduce_memory_proposal_events(
        read_memory_proposal_events(project=project, ledger_path=ledger_path)
    )


def reduce_memory_proposal_events(
    events: Iterable[MemoryProposalLedgerEvent],
) -> tuple[MemoryProposalState, ...]:
    """Reduce proposal events into current pending proposal states."""
    states: dict[str, MemoryProposalState] = {}
    for event in events:
        if isinstance(event, MemoryProposalEvent):
            states[event.proposal_id] = MemoryProposalState(
                proposal_id=event.proposal_id,
                status="pending",
                created_at=event.timestamp,
                updated_at=event.timestamp,
                project=event.project,
                cwd=event.cwd,
                title=event.title,
                target_path=event.target_path,
                keywords=event.keywords,
                author_name=event.author_name,
                author_source=event.author_source,
                artifacts_dir=event.artifacts_dir,
                body_path=event.body_path,
                body_sha256=event.body_sha256,
                body_byte_count=event.body_byte_count,
                evidence=event.evidence,
                warnings=event.warnings,
            )
            continue
        state = states.get(event.proposal_id)
        if state is not None:
            states[event.proposal_id] = _state_with_review_event(state, event)
    return tuple(
        sorted(
            states.values(),
            key=lambda state: (state.created_at, state.proposal_id),
        )
    )


def memory_proposal_state_to_dict(state: MemoryProposalState) -> dict[str, Any]:
    """Return a deterministic JSON-serializable proposal state mapping."""
    return asdict(state)


def memory_proposal_event_to_dict(event: MemoryProposalLedgerEvent) -> dict[str, Any]:
    """Return a deterministic JSON-serializable proposal event mapping."""
    return asdict(event)


def memory_proposal_ledger_event_to_dict(
    event: MemoryProposalLedgerEvent,
) -> dict[str, Any]:
    """Return a deterministic JSON-serializable ledger event mapping."""
    return memory_proposal_event_to_dict(event)


def _append_memory_proposal_event(
    event: MemoryProposalEvent, *, body: str, ledger_path: Path
) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = memory_proposal_lock_path(ledger_path=ledger_path)
    draft_path = Path(event.body_path)
    with locked_file(lock_path, fcntl.LOCK_EX):
        if draft_path.exists():
            raise MemoryProposalError(
                f"memory proposal draft already exists: {draft_path}"
            )
        draft_path.parent.mkdir(parents=True, exist_ok=False)
        draft_path.write_text(body, encoding="utf-8")
        _append_event_to_ledger_unlocked(event, ledger_path)


def _append_event_to_ledger_unlocked(
    event: MemoryProposalLedgerEvent, ledger_path: Path
) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as output_file:
        json.dump(
            memory_proposal_ledger_event_to_dict(event), output_file, sort_keys=True
        )
        output_file.write("\n")
        output_file.flush()


def _ensure_pending_review(state: MemoryProposalState) -> None:
    if state.status != "pending":
        raise MemoryProposalReviewError(
            f"memory proposal {state.proposal_id} is {state.status}; "
            "only pending proposals can be reviewed"
        )


def _approval_body_and_reviewed_path(
    state: MemoryProposalState, *, edited_file: Path | str | None
) -> tuple[str, Path | None]:
    if edited_file is None:
        return _read_required_text(Path(state.body_path), label="proposal draft"), None

    edited_path = Path(edited_file)
    body = _read_required_text(edited_path, label="edited proposal body")
    reviewed_path = _reviewed_body_path(state)
    if edited_path.resolve(strict=False) != reviewed_path.resolve(strict=False):
        reviewed_path.parent.mkdir(parents=True, exist_ok=True)
        reviewed_path.write_text(body, encoding="utf-8")
    return body, reviewed_path


def _reviewed_body_path(state: MemoryProposalState) -> Path:
    return Path(state.body_path).with_name("reviewed.md")


def _read_required_text(path: Path, *, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MemoryProposalBodyError(f"failed to read {label}: {path}") from exc
    except UnicodeError as exc:
        raise MemoryProposalBodyError(
            f"failed to decode {label} as UTF-8: {path}"
        ) from exc


def _canonical_memory_content(
    *, proposal_id: str, keywords: tuple[str, ...], body: str
) -> str:
    lines = ["---"]
    if keywords:
        lines.append("keywords:")
        lines.extend(
            f"  - {json.dumps(keyword, ensure_ascii=True)}" for keyword in keywords
        )
    lines.append(f"source_candidate: {proposal_id}")
    lines.append("---")
    content = "\n".join(lines) + "\n\n" + body
    if not content.endswith("\n"):
        content += "\n"
    return content


def _approval_reachability_warnings(
    state: MemoryProposalState, *, canonical_path: Path, cwd: Path
) -> tuple[ProposalWarning, ...]:
    warnings: list[ProposalWarning] = []
    if not state.keywords:
        warnings.append(
            ProposalWarning(
                code="reachability.missing_keywords",
                message=(
                    "approved memory has no keywords frontmatter; dynamic memory "
                    "auto-discovery will skip it"
                ),
            )
        )

    try:
        from sase.memory.inventory import build_memory_inventory

        inventory = build_memory_inventory(cwd)
        entry = inventory.entry_for(f"memory/{state.target_path}")
    except Exception:
        return tuple(warnings)

    if entry.path.resolve(strict=False) != canonical_path.resolve(strict=False):
        return tuple(warnings)
    if entry.status == "available" and not state.keywords:
        warnings.append(
            ProposalWarning(
                code="reachability.available_only",
                message=(
                    "approved memory is available but not loaded by an @ reference "
                    "and is not dynamically discoverable"
                ),
            )
        )
    return tuple(warnings)


def _state_with_review_event(
    state: MemoryProposalState, event: _MemoryProposalReviewEvent
) -> MemoryProposalState:
    return MemoryProposalState(
        proposal_id=state.proposal_id,
        status=event.event_type,
        created_at=state.created_at,
        updated_at=event.timestamp,
        project=state.project,
        cwd=state.cwd,
        title=state.title,
        target_path=event.target_path,
        keywords=state.keywords,
        author_name=state.author_name,
        author_source=state.author_source,
        artifacts_dir=state.artifacts_dir,
        body_path=state.body_path,
        body_sha256=state.body_sha256,
        body_byte_count=state.body_byte_count,
        evidence=state.evidence,
        warnings=state.warnings,
        reviewed_at=event.timestamp,
        reviewer_user=event.reviewer_user,
        reviewer_hostname=event.reviewer_hostname,
        review_reason=event.reason,
        canonical_path=event.canonical_path,
        reviewed_body_path=event.reviewed_body_path,
    )


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise MemoryProposalError("memory proposal title must not be empty")
    return normalized


def _validate_body(body: str) -> bytes:
    if not body.strip():
        raise MemoryProposalBodyError("memory proposal body must not be empty")
    body_bytes = body.encode("utf-8")
    if len(body_bytes) > MEMORY_PROPOSAL_BODY_MAX_BYTES:
        raise MemoryProposalBodyError("memory proposal body exceeds 256 KiB")
    return body_bytes


def _parse_one_evidence(value: str, *, cwd: Path) -> EvidenceRecord:
    raw = value.strip()
    if not raw:
        raise MemoryProposalEvidenceError("memory proposal evidence must not be blank")

    if raw.startswith("chat:"):
        chat_id = raw.removeprefix("chat:").strip()
        if not chat_id:
            raise MemoryProposalEvidenceError("chat evidence id must not be empty")
        return EvidenceRecord(kind="chat", raw=raw, chat_id=chat_id)

    if raw.startswith("note:"):
        note = raw.removeprefix("note:").strip()
        if not note:
            raise MemoryProposalEvidenceError("note evidence must not be empty")
        return EvidenceRecord(kind="note", raw=raw, note=note)

    if raw.startswith("url:"):
        return _url_evidence(raw.removeprefix("url:").strip(), raw=raw)

    if raw.startswith("http://") or raw.startswith("https://"):
        return _url_evidence(raw, raw=raw)

    return _path_evidence(raw, cwd=cwd)


def _url_evidence(url: str, *, raw: str) -> EvidenceRecord:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise MemoryProposalEvidenceError("url evidence must be an http(s) URL")
    return EvidenceRecord(kind="url", raw=raw, url=url)


def _path_evidence(raw: str, *, cwd: Path) -> EvidenceRecord:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    resolved = path.resolve(strict=False)
    exists = resolved.exists()
    byte_count: int | None = None
    digest: str | None = None
    if exists and resolved.is_file():
        try:
            data = resolved.read_bytes()
        except OSError:
            data = None
        if data is not None:
            byte_count = len(data)
            digest = hashlib.sha256(data).hexdigest()

    return EvidenceRecord(
        kind="path",
        raw=raw,
        path=str(path),
        resolved_path=str(resolved),
        exists=exists,
        byte_count=byte_count,
        sha256=digest,
    )


def _proposal_event_from_mapping(
    data: Mapping[str, Any],
) -> MemoryProposalLedgerEvent | None:
    if data.get("schema_version") != MEMORY_PROPOSAL_SCHEMA_VERSION:
        return None
    event_type = data.get("event_type")
    if event_type != "proposed":
        if event_type in {"approved", "approved_with_edits", "rejected"}:
            return _review_event_from_mapping(data)
        return None
    required_strings = (
        "proposal_id",
        "timestamp",
        "project",
        "cwd",
        "title",
        "target_path",
        "author_name",
        "author_source",
        "body_path",
        "body_sha256",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str):
            return None
    if not isinstance(data.get("body_byte_count"), int):
        return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None
    keywords = _strings_tuple(data.get("keywords"))
    evidence = _evidence_tuple(data.get("evidence"))
    warnings = _warnings_tuple(data.get("warnings"))
    if keywords is None or evidence is None or warnings is None:
        return None

    return MemoryProposalEvent(
        schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
        event_type="proposed",
        proposal_id=data["proposal_id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        title=data["title"],
        target_path=data["target_path"],
        keywords=keywords,
        author_name=data["author_name"],
        author_source=data["author_source"],
        artifacts_dir=artifacts_dir,
        body_path=data["body_path"],
        body_sha256=data["body_sha256"],
        body_byte_count=data["body_byte_count"],
        evidence=evidence,
        warnings=warnings,
    )


def _review_event_from_mapping(
    data: Mapping[str, Any],
) -> _MemoryProposalReviewEvent | None:
    required_strings = (
        "proposal_id",
        "timestamp",
        "project",
        "cwd",
        "reviewer_user",
        "reviewer_hostname",
        "target_path",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str):
            return None
    try:
        canonical_path = _optional_string(data.get("canonical_path"))
        reviewed_body_path = _optional_string(data.get("reviewed_body_path"))
        body_sha256 = _optional_string(data.get("body_sha256"))
        reason = _optional_string(data.get("reason"))
    except TypeError:
        return None
    body_byte_count = data.get("body_byte_count")
    if body_byte_count is not None and not isinstance(body_byte_count, int):
        return None
    event_type = data.get("event_type")
    if event_type not in {"approved", "approved_with_edits", "rejected"}:
        return None

    return _MemoryProposalReviewEvent(
        schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
        event_type=event_type,  # type: ignore[arg-type]
        proposal_id=data["proposal_id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        reviewer_user=data["reviewer_user"],
        reviewer_hostname=data["reviewer_hostname"],
        target_path=data["target_path"],
        canonical_path=canonical_path,
        reviewed_body_path=reviewed_body_path,
        body_sha256=body_sha256,
        body_byte_count=body_byte_count,
        reason=reason,
    )


def _strings_tuple(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    strings: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return None
        strings.append(item)
    return tuple(strings)


def _evidence_tuple(value: Any) -> tuple[EvidenceRecord, ...] | None:
    if not isinstance(value, list):
        return None
    records: list[EvidenceRecord] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        record = _evidence_from_mapping(item)
        if record is None:
            return None
        records.append(record)
    return tuple(records)


def _evidence_from_mapping(data: Mapping[str, Any]) -> EvidenceRecord | None:
    kind = data.get("kind")
    raw = data.get("raw")
    if kind not in {"path", "chat", "url", "note"} or not isinstance(raw, str):
        return None
    try:
        path = _optional_string(data.get("path"))
        resolved_path = _optional_string(data.get("resolved_path"))
        sha256 = _optional_string(data.get("sha256"))
        chat_id = _optional_string(data.get("chat_id"))
        url = _optional_string(data.get("url"))
        note = _optional_string(data.get("note"))
    except TypeError:
        return None
    exists = data.get("exists")
    if exists is not None and not isinstance(exists, bool):
        return None
    byte_count = data.get("byte_count")
    if byte_count is not None and not isinstance(byte_count, int):
        return None
    return EvidenceRecord(
        kind=kind,  # type: ignore[arg-type]
        raw=raw,
        path=path,
        resolved_path=resolved_path,
        exists=exists,
        byte_count=byte_count,
        sha256=sha256,
        chat_id=chat_id,
        url=url,
        note=note,
    )


def _warnings_tuple(value: Any) -> tuple[ProposalWarning, ...] | None:
    if not isinstance(value, list):
        return None
    warnings: list[ProposalWarning] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        code = item.get("code")
        message = item.get("message")
        match = item.get("match")
        if not isinstance(code, str) or not isinstance(message, str):
            return None
        if match is not None and not isinstance(match, str):
            return None
        warnings.append(ProposalWarning(code=code, message=message, match=match))
    return tuple(warnings)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()
