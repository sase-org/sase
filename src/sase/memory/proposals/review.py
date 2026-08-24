"""Review actions for memory proposals."""

from __future__ import annotations

from datetime import UTC, datetime
import fcntl
import hashlib
from pathlib import Path

from sase.content_layout import LayoutCollisionError
from sase.memory.locks import locked_file
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
    discover_memory_notes,
    parse_memory_note_text,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_layout,
    memory_write_root,
)
from sase.memory.proposals.identity import require_proposal_reviewer
from sase.memory.proposals.ledger import (
    append_event_to_ledger_unlocked,
    read_memory_proposals,
    read_memory_proposal_events_unlocked,
    reduce_memory_proposal_events,
    resolve_memory_proposal_id,
)
from sase.memory.proposals.models import (
    MEMORY_PROPOSAL_SCHEMA_VERSION,
    MemoryProposalBodyError,
    MemoryProposalReviewEvent,
    MemoryProposalReviewError,
    MemoryProposalReviewResult,
    MemoryProposalState,
    MemoryProposalTargetError,
    ProposalReviewer,
    ProposalWarning,
)
from sase.memory.proposals.paths import (
    memory_proposal_ledger_path,
    memory_proposal_lock_path,
)
from sase.memory.proposals.validation import (
    event_timestamp,
    validate_body,
    validate_memory_proposal_target,
)


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
    event: MemoryProposalReviewEvent
    state: MemoryProposalState
    with locked_file(
        memory_proposal_lock_path(ledger_path=final_ledger_path), fcntl.LOCK_EX
    ):
        events = read_memory_proposal_events_unlocked(final_ledger_path)
        state = resolve_memory_proposal_id(
            proposal_ref, reduce_memory_proposal_events(events)
        )
        _ensure_pending_review(state)
        event = MemoryProposalReviewEvent(
            schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
            event_type="rejected",
            proposal_id=state.proposal_id,
            timestamp=event_timestamp(now or datetime.now(tz=UTC)),
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
        append_event_to_ledger_unlocked(event, final_ledger_path)
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
    """Approve a pending proposal and create its canonical reference memory file."""
    proposal_reviewer = reviewer or require_proposal_reviewer()
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    final_ledger_path = ledger_path or memory_proposal_ledger_path(
        project, cwd=cwd_path
    )
    event: MemoryProposalReviewEvent
    state: MemoryProposalState
    canonical_path: Path
    reviewed_path: Path | None
    with locked_file(
        memory_proposal_lock_path(ledger_path=final_ledger_path), fcntl.LOCK_EX
    ):
        events = read_memory_proposal_events_unlocked(final_ledger_path)
        state = resolve_memory_proposal_id(
            proposal_ref, reduce_memory_proposal_events(events)
        )
        _ensure_pending_review(state)
        target_path = (
            validate_memory_proposal_target(target)
            if target is not None
            else state.target_path
        )
        compatible_memory = memory_layout(cwd_path)
        legacy_target = compatible_memory.legacy[0].path / target_path
        if legacy_target.exists():
            raise MemoryProposalTargetError(
                f"memory proposal target already exists: {target_path}"
            )
        try:
            selected_memory = compatible_memory.resolve_read("project memory")
        except LayoutCollisionError as exc:
            raise MemoryProposalTargetError(str(exc)) from exc
        if (
            selected_memory is not None
            and selected_memory != compatible_memory.canonical.path
        ):
            raise MemoryProposalTargetError(
                "legacy memory content must be migrated with `sase memory init` "
                "before approving a proposal"
            )
        canonical_path = memory_write_root(cwd_path) / target_path
        body, reviewed_path = _approval_body_and_reviewed_path(
            state,
            edited_file=edited_file,
        )
        body_bytes = validate_body(body)
        body_sha256 = hashlib.sha256(body_bytes).hexdigest()
        canonical_body = _canonical_memory_content(
            proposal_id=state.proposal_id,
            title=state.title,
            body=body,
            parent=_memory_proposal_parent(body, cwd=cwd_path),
        )
        canonical_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with canonical_path.open("x", encoding="utf-8") as output_file:
                output_file.write(canonical_body)
        except FileExistsError as exc:
            raise MemoryProposalTargetError(
                f"memory proposal target already exists: {target_path}"
            ) from exc

        event = MemoryProposalReviewEvent(
            schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
            event_type="approved_with_edits" if edited_file is not None else "approved",
            proposal_id=state.proposal_id,
            timestamp=event_timestamp(now or datetime.now(tz=UTC)),
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
        append_event_to_ledger_unlocked(event, final_ledger_path)
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


def _memory_proposal_parent(body: str, *, cwd: Path) -> str:
    note = parse_memory_note_text(body, CANONICAL_MEMORY_RELATIVE_ROOT / "proposal.md")
    if note.parent_source == "missing":
        return AGENTS_PARENT
    if note.parent_source == "invalid":
        raise MemoryProposalBodyError("memory proposal parent must be a string")

    parent = canonical_memory_reference(note.parent).as_posix()
    if parent == AGENTS_PARENT:
        return parent

    existing_notes = {
        existing.relative_path: existing for existing in discover_memory_notes(cwd)
    }
    parent_note = existing_notes.get(parent)
    if parent_note is None:
        raise MemoryProposalBodyError(
            f"memory proposal parent does not exist: {parent}"
        )
    if parent_note.type != "reference":
        raise MemoryProposalBodyError(
            f"memory proposal parent is not a reference memory note: {parent}"
        )
    return parent


def _canonical_memory_content(
    *, proposal_id: str, title: str, body: str, parent: str = AGENTS_PARENT
) -> str:
    content = apply_memory_frontmatter(
        body,
        note_type="reference",
        parent=parent,
        description=title,
        extra={"source_candidate": proposal_id},
    )
    if not content.endswith("\n"):
        content += "\n"
    return content


def _approval_reachability_warnings(
    state: MemoryProposalState, *, canonical_path: Path, cwd: Path
) -> tuple[ProposalWarning, ...]:
    warnings: list[ProposalWarning] = []
    try:
        from sase.memory.inventory import build_memory_inventory

        inventory = build_memory_inventory(cwd)
        entry = inventory.entry_for(
            (CANONICAL_MEMORY_RELATIVE_ROOT / state.target_path).as_posix()
        )
    except Exception:
        return tuple(warnings)

    if entry.path.resolve(strict=False) != canonical_path.resolve(strict=False):
        return tuple(warnings)
    if entry.status == "available":
        warnings.append(
            ProposalWarning(
                code="reachability.available_only",
                message=(
                    "approved memory is available but not loaded by an @ reference"
                ),
            )
        )
    return tuple(warnings)
