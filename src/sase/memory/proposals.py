"""Proposal storage for ``sase memory write``."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
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
ProposalEventType = Literal["proposed"]
ProposalStatus = Literal["pending"]

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
class MemoryProposalEvent:
    """Append-only event for the memory proposal ledger."""

    schema_version: int
    event_type: ProposalEventType
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


@dataclass(frozen=True)
class MemoryProposalWriteResult:
    """Result returned after appending a memory proposal."""

    event: MemoryProposalEvent
    state: MemoryProposalState
    ledger_path: Path
    lock_path: Path
    draft_path: Path


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
) -> tuple[MemoryProposalEvent, ...]:
    """Read proposal ledger events, skipping malformed JSONL rows."""
    path = ledger_path or memory_proposal_ledger_path(project)
    with locked_file(memory_proposal_lock_path(ledger_path=path), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[MemoryProposalEvent] = []
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
    events: Iterable[MemoryProposalEvent],
) -> tuple[MemoryProposalState, ...]:
    """Reduce proposal events into current pending proposal states."""
    states: dict[str, MemoryProposalState] = {}
    for event in events:
        if event.event_type != "proposed":
            continue
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
    return tuple(
        sorted(
            states.values(),
            key=lambda state: (state.created_at, state.proposal_id),
        )
    )


def memory_proposal_state_to_dict(state: MemoryProposalState) -> dict[str, Any]:
    """Return a deterministic JSON-serializable proposal state mapping."""
    return asdict(state)


def memory_proposal_event_to_dict(event: MemoryProposalEvent) -> dict[str, Any]:
    """Return a deterministic JSON-serializable proposal event mapping."""
    return asdict(event)


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
        with ledger_path.open("a", encoding="utf-8") as output_file:
            json.dump(memory_proposal_event_to_dict(event), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()


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


def _proposal_event_from_mapping(data: Mapping[str, Any]) -> MemoryProposalEvent | None:
    if data.get("schema_version") != MEMORY_PROPOSAL_SCHEMA_VERSION:
        return None
    if data.get("event_type") != "proposed":
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
