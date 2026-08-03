"""Rendering and formatting helpers for the memory review TUI."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from rich.text import Text

from sase.core.time import parse_local
from sase.memory.proposals import (
    EvidenceRecord,
    MemoryProposalLedgerEvent,
    MemoryProposalState,
)
from sase.memory.review_tui._models import TargetSummary


def preview_text(state: MemoryProposalState, target: TargetSummary) -> Text:
    text = Text()
    text.append(f"{state.title}\n", style="bold")
    text.append(f"id: {state.proposal_id}\n")
    text.append(f"author: {state.author_name} ({state.author_source})\n")
    text.append(f"target: {target.target_path} ")
    text.append("(exists)\n" if target.exists else "(available)\n")
    text.append(f"evidence: {len(state.evidence)} item(s)\n")
    if state.warnings:
        text.append("\nwarnings:\n", style="bold yellow")
        for warning in state.warnings:
            text.append(f"- {warning.code}: {warning.message}\n")
    text.append(
        "\nPress enter or d for evidence, target, and audit details.\n", style="dim"
    )
    return text


def detail_text(
    state: MemoryProposalState,
    target: TargetSummary,
    events: Iterable[MemoryProposalLedgerEvent],
) -> Text:
    text = Text()
    text.append(f"{state.title}\n", style="bold")
    text.append(f"id: {state.proposal_id}\n")
    text.append(f"status: {state.status}\n")
    text.append(f"created: {state.created_at}\n")
    text.append(f"author: {state.author_name} ({state.author_source})\n")

    text.append("\nEvidence\n", style="bold")
    for line in _evidence_lines(state.evidence):
        text.append(line + "\n")

    text.append("\nTarget\n", style="bold")
    text.append(f"path: {target.target_path}\n")
    text.append(f"canonical: {target.canonical_path}\n")
    if target.error:
        text.append(f"status: exists, failed to read: {target.error}\n", style="red")
    else:
        text.append("status: exists\n" if target.exists else "status: available\n")
    if target.diff:
        text.append("diff:\n", style="bold")
        for line in target.diff[:120]:
            style = (
                "green"
                if line.startswith("+")
                else "red"
                if line.startswith("-")
                else ""
            )
            text.append(line + "\n", style=style)
        if len(target.diff) > 120:
            text.append(f"... {len(target.diff) - 120} more diff lines\n", style="dim")

    if state.warnings:
        text.append("\nWarnings\n", style="bold yellow")
        for warning in state.warnings:
            text.append(f"- {warning.code}: {warning.message}\n")

    text.append("\nAudit\n", style="bold")
    audit_lines = _proposal_audit_lines(state.proposal_id, events)
    for line in audit_lines:
        text.append(line + "\n")
    return text


def _evidence_lines(evidence: Iterable[EvidenceRecord]) -> tuple[str, ...]:
    lines: list[str] = []
    for record in evidence:
        if record.kind == "path":
            status = "exists" if record.exists else "missing"
            detail = record.resolved_path or record.path or record.raw
            parts = [f"- path {status}: {detail}"]
            if record.byte_count is not None:
                parts.append(f"bytes={record.byte_count}")
            if record.sha256:
                parts.append(f"sha256={record.sha256[:12]}")
            lines.append("  ".join(parts))
            excerpt = _path_excerpt(record.resolved_path)
            if excerpt:
                lines.append(f"  excerpt: {excerpt}")
            continue
        if record.kind == "chat":
            lines.append(f"- chat: {record.chat_id}")
            continue
        if record.kind == "url":
            lines.append(f"- url: {record.url}")
            continue
        if record.kind == "note":
            lines.append(f"- note: {record.note}")
    return tuple(lines)


def _proposal_audit_lines(
    proposal_id: str,
    events: Iterable[MemoryProposalLedgerEvent],
) -> tuple[str, ...]:
    lines: list[str] = []
    for event in events:
        if event.proposal_id != proposal_id:
            continue
        event_type = event.event_type
        actor = getattr(event, "author_name", None)
        if actor is None:
            actor = (
                f"{getattr(event, 'reviewer_user', 'unknown')}@"
                f"{getattr(event, 'reviewer_hostname', 'unknown')}"
            )
        line = f"- {event.timestamp} {event_type} by {actor}"
        reason = getattr(event, "reason", None)
        if reason:
            line += f": {reason}"
        lines.append(line)
    return tuple(lines) or ("- no ledger events found",)


def _path_excerpt(path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    line = next(
        (candidate.strip() for candidate in text.splitlines() if candidate.strip()), ""
    )
    if len(line) > 96:
        return line[:93] + "..."
    return line


def read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def format_time_or_age(timestamp: str) -> str:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    now = datetime.now(tz=UTC)
    seconds = max(0, int((now - parsed.astimezone(UTC)).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 48:
        return f"{hours}h"
    local = parse_local(parsed)
    assert local is not None
    return local.strftime("%Y-%m-%d")
