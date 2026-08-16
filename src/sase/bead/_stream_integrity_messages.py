"""Operator-facing wording for bead event-stream integrity failures.

Publication guards phrase a violation as a refusal ("cannot publish ...")
because the caller can still fix the worktree; history diagnostics phrase
the same violation as a report on a commit that already landed.
"""

from __future__ import annotations


def rewrite_message(
    stream_id: str,
    event_number: int | None,
    diagnosis: str | None = None,
) -> str:
    """Phrase a refusal to publish a stream that rewrote an ancestor event."""
    number = event_number if event_number is not None else 0
    message = (
        "cannot publish non-append-only bead event stream "
        f"{stream_id}: worktree rewrote ancestor event {number}"
    )
    if diagnosis:
        return f"{message} ({diagnosis})"
    return message


def missing_message(
    stream_id: str,
    first_event: int | None,
    last_event: int | None,
) -> str:
    """Phrase a refusal to publish a HEAD that dropped ancestor events."""
    first = first_event if first_event is not None else 0
    last = last_event if last_event is not None else first
    return (
        "cannot publish non-append-only bead event stream "
        f"{stream_id}: HEAD missing ancestor events {first}-{last}"
    )


def rewrite_history_message(
    stream_id: str,
    event_number: int | None,
    sha: str,
    subject: str,
) -> str:
    """Report a committed rewrite of an already-published event."""
    number = event_number if event_number is not None else 0
    return (
        f"ERROR: bead event stream {stream_id} rewrote event {number}; "
        f"first offending commit {_short_sha(sha)} ({_subject(subject)})"
    )


def missing_history_message(
    stream_id: str,
    first_event: int | None,
    last_event: int | None,
    ancestor_sha: str,
    sha: str,
    subject: str,
) -> str:
    """Report a committed shrink relative to the stream's own ancestor."""
    first = first_event if first_event is not None else 0
    last = last_event if last_event is not None else first
    return (
        f"ERROR: bead event stream {stream_id} is shorter than its own "
        f"history: missing events {first}-{last} present in ancestor "
        f"{_short_sha(ancestor_sha)}; first offending commit "
        f"{_short_sha(sha)} ({_subject(subject)})"
    )


def _short_sha(sha: str) -> str:
    return sha[:12] if len(sha) > 12 else sha


def _subject(subject: str) -> str:
    text = subject.strip() or "unknown subject"
    if len(text) > 80:
        return text[:77] + "..."
    return text
