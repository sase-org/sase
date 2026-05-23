"""Creation flow for memory proposals."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
import hashlib
from pathlib import Path

from sase.main.init_memory.config import project_memory_name
from sase.memory._proposal_identity import require_proposal_author
from sase.memory._proposal_ledger import (
    append_memory_proposal_event,
    memory_proposal_ledger_path,
    memory_proposal_lock_path,
    reduce_memory_proposal_events,
)
from sase.memory._proposal_models import (
    MEMORY_PROPOSAL_SCHEMA_VERSION,
    MemoryProposalEvent,
    MemoryProposalWriteResult,
    ProposalAuthor,
)
from sase.memory._proposal_validation import (
    proposal_event_timestamp,
    normalize_proposal_title,
    validate_proposal_body,
    validate_proposal_id,
    build_memory_proposal_warnings,
    generate_memory_proposal_id,
    normalize_proposal_keywords,
    parse_memory_proposal_evidence,
    validate_memory_proposal_target,
)
from sase.telemetry.metrics import MEMORY_PROPOSALS_PROPOSED


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
    normalized_title = normalize_proposal_title(title)
    target_path = validate_memory_proposal_target(target, slug=slug)
    evidence = parse_memory_proposal_evidence(evidence_values, cwd=cwd_path)
    normalized_keywords = normalize_proposal_keywords(keywords)
    proposal_author = author or require_proposal_author(manual_author=manual_author)
    body_bytes = validate_proposal_body(body)
    body_sha256 = hashlib.sha256(body_bytes).hexdigest()
    timestamp = proposal_event_timestamp(now or datetime.now(tz=UTC))
    final_proposal_id = proposal_id or generate_memory_proposal_id(now=now)
    validate_proposal_id(final_proposal_id)
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

    append_memory_proposal_event(event, body=body, ledger_path=final_ledger_path)
    state = reduce_memory_proposal_events((event,))[0]
    MEMORY_PROPOSALS_PROPOSED.inc()
    return MemoryProposalWriteResult(
        event=event,
        state=state,
        ledger_path=final_ledger_path,
        lock_path=lock_path,
        draft_path=draft_path,
    )
