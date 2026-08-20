"""Off-thread write and publish tasks for the Memory panel.

Every function here mutates disk or runs ``sase memory init`` and must only
ever run inside a session worker, never on the event loop -- see the TUI
performance rules in ``sase/memory/tui_perf.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.ace.tui.actions.proc_actions import TrackedProcResult
from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeRef,
    MemoryScopeSnapshot,
    invalidate_memory_scope,
    load_memory_scope_snapshot,
)
from sase.memory.mutation import (
    MemoryConflictError,
    MemoryGeneratedNoteError,
    MemoryMutationError,
    MemoryMutationOutcome,
    MemoryValidationError,
    create_memory_note,
    delete_memory_note,
    update_memory_note,
)
from sase.noninteractive_subprocess import run_noninteractive

from .memory_panel_publish import format_memory_publish_failure

MemoryWriteKind = Literal["add", "edit", "delete"]


@dataclass(frozen=True, slots=True)
class MemoryWritePayload:
    """Outcome of one Memory-panel create/update/delete worker."""

    kind: MemoryWriteKind
    scope_key: str
    error: str | None = None
    outcome: MemoryMutationOutcome | None = None
    snapshot: MemoryScopeSnapshot | None = None
    preferred_note: str | None = None
    offer_editor: bool = False


@dataclass(frozen=True, slots=True)
class MemoryPublishPayload:
    """Outcome of one Memory-panel ``sase memory init`` worker."""

    scope_key: str
    error: str | None = None


def run_memory_panel_write(
    *,
    kind: MemoryWriteKind,
    scope: MemoryScopeRef,
    stem: str,
    relative_path: str,
    note_type: str,
    parent: str,
    description: str,
    expected_digest: str,
    preferred_note: str | None,
) -> TrackedProcResult[MemoryWritePayload]:
    """Apply one create/update/delete and reload that scope's snapshot.

    Called only from a session worker: disk writes and the snapshot reload
    must stay off the event loop.
    """
    cleaned_description = description.strip() or None
    try:
        if kind == "add":
            outcome = create_memory_note(
                scope_key=scope.key,
                content_root=scope.content_root,
                stem=stem,
                note_type=note_type,
                parent=parent,
                description=cleaned_description,
                scope_kind=scope.kind,
            )
        elif kind == "edit":
            outcome = update_memory_note(
                scope_key=scope.key,
                content_root=scope.content_root,
                relative_path=relative_path,
                note_type=note_type,
                parent=parent,
                description=cleaned_description,
                expected_digest=expected_digest,
                scope_kind=scope.kind,
            )
        else:
            outcome = delete_memory_note(
                scope_key=scope.key,
                content_root=scope.content_root,
                relative_path=relative_path,
                expected_digest=expected_digest,
                scope_kind=scope.kind,
            )
    except MemoryValidationError as exc:
        return TrackedProcResult(
            False,
            _validation_message(exc),
            payload=MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="validation"
            ),
        )
    except MemoryConflictError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="conflict"
            ),
        )
    except MemoryGeneratedNoteError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="generated"
            ),
        )
    except MemoryMutationError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=MemoryWritePayload(kind=kind, scope_key=scope.key, error="other"),
        )
    invalidate_memory_scope(scope.key)
    snapshot = load_memory_scope_snapshot(scope)
    preferred: str | None
    if kind == "delete":
        preferred = preferred_note
    else:
        preferred = outcome.relative_path
    return TrackedProcResult(
        True,
        _success_message(kind, outcome, scope.display_name),
        payload=MemoryWritePayload(
            kind=kind,
            scope_key=scope.key,
            outcome=outcome,
            snapshot=snapshot,
            preferred_note=preferred,
            offer_editor=kind == "add",
        ),
    )


def run_memory_panel_publish(
    *,
    scope: MemoryScopeRef,
    argv: list[str],
    cwd: Path,
) -> TrackedProcResult[MemoryPublishPayload]:
    """Run ``sase memory init`` off the event loop and return its outcome."""
    from subprocess import TimeoutExpired

    try:
        completed = run_noninteractive(argv, cwd=cwd)
    except TimeoutExpired:
        return TrackedProcResult(
            False,
            format_memory_publish_failure(None, timeout=True),
            payload=MemoryPublishPayload(scope_key=scope.key, error="timeout"),
        )
    except OSError as exc:
        return TrackedProcResult(
            False,
            f"could not run sase memory init: {exc}",
            payload=MemoryPublishPayload(scope_key=scope.key, error="other"),
        )
    if completed.returncode != 0:
        return TrackedProcResult(
            False,
            format_memory_publish_failure(completed),
            payload=MemoryPublishPayload(scope_key=scope.key, error="command"),
        )
    return TrackedProcResult(
        True,
        f"Published memory notes for {scope.display_name}.",
        payload=MemoryPublishPayload(scope_key=scope.key),
    )


def _success_message(
    kind: MemoryWriteKind,
    outcome: MemoryMutationOutcome,
    scope_display_name: str,
) -> str:
    if kind == "add":
        return f'Added "{outcome.stem}" to {scope_display_name}.'
    if kind == "edit":
        return f'Updated "{outcome.stem}" in {scope_display_name}.'
    backup = f" Backup: {outcome.backup_path}." if outcome.backup_path else ""
    return f'Deleted "{outcome.stem}" from {scope_display_name}.{backup}'


def _validation_message(exc: MemoryValidationError) -> str:
    if not exc.validation.by_field:
        return str(exc)
    field, messages = next(iter(exc.validation.by_field.items()))
    if not messages:
        return str(exc)
    return f"{field}: {messages[0]}"


__all__ = [
    "MemoryPublishPayload",
    "MemoryWriteKind",
    "MemoryWritePayload",
    "run_memory_panel_publish",
    "run_memory_panel_write",
]
