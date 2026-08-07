"""Per-attempt execution journal for notification gate branches.

An AND branch runs its option commands one at a time, so a failure partway
through leaves earlier commands already executed. Without a record of that,
a second submission silently re-runs work that already happened. The journal
is that record: one append-only line per attempt boundary, written under the
bundle's ``.response.lock`` beside the response it may eventually produce.

Repeatable non-terminal actions append an ``operation_ran`` record here too.
Those carry their own one-off ``attempt_id`` and never open an attempt, so
they never affect retry resolution; they are the audit trail for what a
reviewer ran before deciding.

Raw submitted input is never written here. Input is reduced to a digest,
which is all a retry needs to decide whether a second submission is the same
submission, and which keeps secret-typed fields out of durable audit data.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase.notification_gates.durability import (
    canonical_json_bytes,
    fsync_dir,
    sha256_bytes,
)

EXECUTION_JOURNAL_FILENAME = "journal.jsonl"
EXECUTION_JOURNAL_SCHEMA_VERSION = 1

_TERMINAL_EVENTS = frozenset({"attempt_completed", "attempt_superseded"})


@dataclass(frozen=True)
class IncompleteAttempt:
    """One started attempt that neither finished nor was superseded."""

    attempt_id: str
    request_hash: str
    selected_option_ids: tuple[str, ...]
    input_digests: Mapping[str, str]
    completed_option_ids: tuple[str, ...] = ()
    failed_option_ids: tuple[str, ...] = ()
    results: Mapping[str, Any] = field(default_factory=dict)

    def matches(
        self,
        *,
        request_hash: str,
        selected_option_ids: Sequence[str],
        input_digests: Mapping[str, str],
    ) -> bool:
        """Whether a new submission is a retry of this attempt rather than a new one."""
        return (
            self.request_hash == request_hash
            and self.selected_option_ids == tuple(selected_option_ids)
            and dict(self.input_digests) == dict(input_digests)
        )

    def describe(self) -> str:
        """Render the completed and failed option ids for an operator message."""
        completed = ", ".join(self.completed_option_ids) or "none"
        failed = ", ".join(self.failed_option_ids) or "none"
        return f"completed: {completed}; failed: {failed}"


def value_digest(value: object) -> str:
    """Return the digest recorded in place of a raw journal value."""
    return sha256_bytes(canonical_json_bytes(value))


def append_journal_event(
    bundle_path: Path,
    *,
    attempt_id: str,
    request_hash: str,
    event: str,
    option_id: str | None = None,
    operation_id: str | None = None,
    input_digest: str | None = None,
    result_digest: str | None = None,
    result: object | None = None,
    selected_option_ids: Sequence[str] | None = None,
    input_digests: Mapping[str, str] | None = None,
    code: str | None = None,
) -> None:
    """Append one attempt-boundary record; never raises into the caller's path."""
    record: dict[str, Any] = {
        "schema_version": EXECUTION_JOURNAL_SCHEMA_VERSION,
        "attempt_id": attempt_id,
        "request_hash": request_hash,
        "event": event,
        "option_id": option_id,
        "operation_id": operation_id,
        "input_digest": input_digest,
        "result_digest": result_digest,
        "code": code,
        "at_unix": time.time(),
    }
    if selected_option_ids is not None:
        record["selected_option_ids"] = list(selected_option_ids)
    if input_digests is not None:
        record["input_digests"] = dict(input_digests)
    if event == "option_completed":
        record["result"] = result
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    line = canonical_json_bytes(record) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def _read_journal_events(bundle_path: Path) -> tuple[dict[str, Any], ...]:
    """Return every well-formed journal record in append order."""
    path = bundle_path / EXECUTION_JOURNAL_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        return ()
    except OSError:
        return ()
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            value = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("attempt_id"), str):
            events.append(value)
    return tuple(events)


def incomplete_attempt(bundle_path: Path) -> IncompleteAttempt | None:
    """Return the newest started attempt that never reached a terminal event."""
    events = _read_journal_events(bundle_path)
    started: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    terminal: set[str] = set()
    for record in events:
        attempt_id = str(record["attempt_id"])
        event = record.get("event")
        if event == "attempt_started":
            started[attempt_id] = record
            order.append(attempt_id)
        elif event in _TERMINAL_EVENTS:
            terminal.add(attempt_id)
    open_ids = [
        attempt_id
        for attempt_id in order
        if attempt_id not in terminal and attempt_id in started
    ]
    if not open_ids:
        return None
    attempt_id = open_ids[-1]
    start = started[attempt_id]
    completed: list[str] = []
    failed: list[str] = []
    results: dict[str, Any] = {}
    for record in events:
        if str(record["attempt_id"]) != attempt_id:
            continue
        option_id = record.get("option_id")
        if not isinstance(option_id, str):
            continue
        if record.get("event") == "option_completed":
            if option_id not in completed:
                completed.append(option_id)
            results[option_id] = record.get("result")
        elif record.get("event") == "option_failed" and option_id not in failed:
            failed.append(option_id)
    raw_selected = start.get("selected_option_ids")
    raw_digests = start.get("input_digests")
    return IncompleteAttempt(
        attempt_id=attempt_id,
        request_hash=str(start.get("request_hash") or ""),
        selected_option_ids=(
            tuple(str(value) for value in raw_selected)
            if isinstance(raw_selected, list)
            else ()
        ),
        input_digests=(
            {str(key): str(value) for key, value in raw_digests.items()}
            if isinstance(raw_digests, dict)
            else {}
        ),
        completed_option_ids=tuple(completed),
        failed_option_ids=tuple(failed),
        results=results,
    )


__all__ = [
    "EXECUTION_JOURNAL_FILENAME",
    "EXECUTION_JOURNAL_SCHEMA_VERSION",
    "IncompleteAttempt",
    "append_journal_event",
    "incomplete_attempt",
    "value_digest",
]
