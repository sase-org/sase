"""Validation and parsing helpers for memory proposals."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import hashlib
from pathlib import Path
import re
from urllib.parse import urlparse
from uuid import uuid4

from sase.memory.proposals.models import (
    MEMORY_PROPOSAL_BODY_MAX_BYTES,
    MEMORY_PROPOSAL_BODY_WARN_BYTES,
    EvidenceRecord,
    MemoryProposalBodyError,
    MemoryProposalError,
    MemoryProposalEvidenceError,
    MemoryProposalTargetError,
    ProposalWarning,
)

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


def validate_memory_proposal_target(
    target: str | None = None, *, slug: str | None = None
) -> str:
    """Validate a one-level flat ``<slug>.md`` proposal target path."""
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
        return f"{normalized_slug}.md"

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
    if len(path.parts) != 1:
        raise MemoryProposalTargetError(
            "memory proposal target must be a one-level <slug>.md path"
        )
    if path.suffix != ".md":
        raise MemoryProposalTargetError("memory proposal target must end with .md")
    slug_value = path.stem
    if not _SLUG_RE.fullmatch(slug_value):
        raise MemoryProposalTargetError(
            "memory proposal target slug must match [a-z0-9][a-z0-9_-]*"
        )
    return path.as_posix()


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


def generate_memory_proposal_id(*, now: datetime | None = None) -> str:
    """Generate a proposal id shaped like ``mem-YYYYMMDD-HHMMSS-<8hex>``."""
    timestamp = now or datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    stamp = timestamp.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"mem-{stamp}-{uuid4().hex[:8]}"


def validate_proposal_id(proposal_id: str) -> None:
    if not _PROPOSAL_ID_RE.fullmatch(proposal_id):
        raise MemoryProposalError(
            "memory proposal id must match mem-YYYYMMDD-HHMMSS-<8hex>"
        )


def event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


def validate_body(body: str) -> bytes:
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
