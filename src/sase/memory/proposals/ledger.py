"""JSONL ledger IO and event reduction for memory proposals."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict
import fcntl
import json
from pathlib import Path
from typing import Any

from sase.memory.locks import locked_file
from sase.memory.proposals.models import (
    MEMORY_PROPOSAL_SCHEMA_VERSION,
    EvidenceRecord,
    MemoryProposalError,
    MemoryProposalEvent,
    MemoryProposalLedgerEvent,
    MemoryProposalLookupError,
    MemoryProposalReviewEvent,
    MemoryProposalState,
    ProposalWarning,
)
from sase.memory.proposals.paths import (
    memory_proposal_ledger_path,
    memory_proposal_lock_path,
)


def resolve_memory_proposal_id(
    proposal_ref: str, states: Iterable[MemoryProposalState]
) -> MemoryProposalState:
    """Resolve an exact proposal id or unambiguous id prefix."""
    ref = proposal_ref.strip()
    if not ref:
        raise MemoryProposalLookupError("memory proposal id must not be empty")

    states_tuple = tuple(states)
    for state in states_tuple:
        if state.proposal_id == ref:
            return state

    matches = tuple(
        state for state in states_tuple if state.proposal_id.startswith(ref)
    )
    if not matches:
        raise MemoryProposalLookupError(f"unknown memory proposal id: {ref}")
    if len(matches) > 1:
        matching_ids = ", ".join(state.proposal_id for state in matches)
        raise MemoryProposalLookupError(
            f"ambiguous memory proposal id prefix: {ref} ({matching_ids})"
        )
    return matches[0]


def read_memory_proposal_events(
    *,
    project: str | None = None,
    ledger_path: Path | None = None,
) -> tuple[MemoryProposalLedgerEvent, ...]:
    """Read proposal ledger events, skipping malformed JSONL rows."""
    path = ledger_path or memory_proposal_ledger_path(project)
    with locked_file(memory_proposal_lock_path(ledger_path=path), fcntl.LOCK_SH):
        return read_memory_proposal_events_unlocked(path)


def read_memory_proposal_events_unlocked(
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


def append_memory_proposal_event(
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
        append_event_to_ledger_unlocked(event, ledger_path)


def append_event_to_ledger_unlocked(
    event: MemoryProposalLedgerEvent, ledger_path: Path
) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as output_file:
        json.dump(
            memory_proposal_ledger_event_to_dict(event), output_file, sort_keys=True
        )
        output_file.write("\n")
        output_file.flush()


def _state_with_review_event(
    state: MemoryProposalState, event: MemoryProposalReviewEvent
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
    evidence = _evidence_tuple(data.get("evidence"))
    warnings = _warnings_tuple(data.get("warnings"))
    if evidence is None or warnings is None:
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
) -> MemoryProposalReviewEvent | None:
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

    return MemoryProposalReviewEvent(
        schema_version=MEMORY_PROPOSAL_SCHEMA_VERSION,
        event_type=event_type,
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
        kind=kind,
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
