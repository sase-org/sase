"""Add/edit/delete/publish write surfaces for the Memory panel.

Writes go through the app's session-worker queue, call the shared memory
mutation engine off the event loop, and apply reselect / toast /
unpublished / publish-offer effects back on the UI thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
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
from sase.memory.notes import MemoryNote
from sase.memory.text_filter import filter_memory_notes
from sase.noninteractive_subprocess import run_noninteractive

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .memory_panel_add import MemoryNoteFormDraft, MemoryNoteFormModal
from .memory_panel_publish import (
    MemoryPublishChoice,
    MemoryPublishModal,
    format_memory_publish_failure,
    memory_publish_argv,
    memory_publish_cwd,
    memory_publish_subject,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.worker import Worker

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode
else:
    _MixinBase = object

_MemoryWriteKind = Literal["add", "edit", "delete"]


@dataclass(frozen=True, slots=True)
class _MemoryWritePayload:
    kind: _MemoryWriteKind
    scope_key: str
    error: str | None = None
    outcome: MemoryMutationOutcome | None = None
    snapshot: MemoryScopeSnapshot | None = None
    preferred_note: str | None = None
    offer_editor: bool = False


@dataclass(frozen=True, slots=True)
class _MemoryPublishPayload:
    scope_key: str
    error: str | None = None


def _build_memory_delete_subject(
    note: MemoryNote,
    *,
    child_count: int,
) -> str:
    """Build the confirm-dialog subject for deleting *note*."""
    first_line = next(
        (
            line.strip()
            for line in (note.description or "").splitlines()
            if line.strip()
        ),
        "",
    )
    tier = "1 (short)" if note.type == "short" else "2 (long)"
    child_word = "child" if child_count == 1 else "children"
    lines = [
        f"Note: {note.relative_path}",
        f"Tier: {tier}",
        f"Description: {first_line or '(empty)'}",
        f"Children: {child_count} {child_word}",
    ]
    if note.type == "short":
        lines.append(
            "WARNING: deleting a short note removes always-loaded agent context."
        )
    return "\n".join(lines)


def _build_child_blocked_delete_message(children: Sequence[MemoryNote]) -> str:
    """Explain why a note with children cannot be deleted."""
    named = ", ".join(child.relative_path for child in children)
    return (
        "This note has children and cannot be deleted until they are "
        f"reparented: {named}"
    )


def _neighbor_note_after_delete(paths: Sequence[str], deleted_path: str) -> str | None:
    """Return the note that should stay selected after *deleted_path* is removed."""
    visible = list(paths)
    try:
        index = visible.index(deleted_path)
    except ValueError:
        return visible[-1] if visible else None
    remaining = [path for path in visible if path != deleted_path]
    if not remaining:
        return None
    if index >= len(remaining):
        return remaining[-1]
    return remaining[index]


def _children_of(
    notes: Sequence[MemoryNote], relative_path: str
) -> tuple[MemoryNote, ...]:
    children = [note for note in notes if note.parent == relative_path]
    return tuple(sorted(children, key=lambda note: note.relative_path))


class MemoryPanelActionsMixin(_MixinBase):
    """Add/edit forms, delete confirmation, and publish for MemoryPanel."""

    if TYPE_CHECKING:
        _accent: str
        _current_note: str | None
        _filter_bodies: bool
        _filter_text: str
        _loading: bool
        _pending_delete_neighbor: str | None
        _pending_delete_path: str | None
        _ring: tuple[MemoryScopeRef, ...]
        _rows: tuple[MemoryRailNode, ...]
        _scope_index: int
        _scope_worker: Worker[MemoryScopeSnapshot] | None
        _snapshot: MemoryScopeSnapshot | None
        _unpublished_scopes: set[str]
        _write_busy: bool
        is_mounted: bool
        app: Any

        def _apply_snapshot(
            self,
            snapshot: MemoryScopeSnapshot | None,
            *,
            preferred_note: str | None,
        ) -> None: ...

        def _clear_scope_unpublished(self, scope_key: str) -> None: ...

        def _filter_input(self) -> Any: ...

        def _mark_scope_unpublished(self, scope_key: str | None = None) -> None: ...

        def _selected_is_writable(self) -> bool: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

        def _start_scope_load(self) -> None: ...

        def _update_footer(self) -> None: ...

        def _update_header(self) -> None: ...

        def action_open_source(self) -> None: ...

    def action_add_note(self) -> None:
        if self._loading or self._write_busy or not self._ring:
            return
        scope = self._current_scope()
        if scope is None:
            return
        notes = self._snapshot.notes if self._snapshot is not None else ()
        self.app.push_screen(
            MemoryNoteFormModal(
                mode="add",
                existing_notes=notes,
                scope_display_name=scope.display_name,
                include_project_memory=scope.kind == "project",
                accent=self._accent,
            ),
            self._on_add_draft,
        )

    def action_edit_note(self) -> None:
        if self._loading or self._write_busy:
            return
        node = self._selected_row()
        snapshot = self._snapshot
        scope = self._current_scope()
        if node is None or snapshot is None or scope is None:
            return
        if node.note.relative_path in snapshot.generated_paths:
            self.app.notify(
                f"generated memory note is read-only: {node.note.relative_path}",
                severity="warning",
            )
            return
        note = node.note
        note_type = note.type if note.type in {"short", "long"} else "long"
        self.app.push_screen(
            MemoryNoteFormModal(
                mode="edit",
                existing_notes=snapshot.notes,
                scope_display_name=scope.display_name,
                include_project_memory=scope.kind == "project",
                initial_stem=note.path.stem,
                initial_type=note_type,
                initial_parent=note.parent,
                initial_description=note.description or "",
                current_relative_path=note.relative_path,
                accent=self._accent,
            ),
            self._on_edit_draft,
        )

    def action_delete_note(self) -> None:
        if self._loading or self._write_busy:
            return
        node = self._selected_row()
        snapshot = self._snapshot
        if node is None or snapshot is None:
            return
        if node.note.relative_path in snapshot.generated_paths:
            self.app.notify(
                f"generated memory note is read-only: {node.note.relative_path}",
                severity="warning",
            )
            return
        children = _children_of(snapshot.notes, node.note.relative_path)
        if children:
            self.app.push_screen(
                ConfirmActionModal(
                    "Cannot delete memory note",
                    _build_child_blocked_delete_message(children),
                    subject="\n".join(child.relative_path for child in children),
                    kind=ConfirmKind.NEUTRAL,
                    confirm_label="OK",
                    cancel_label="Close",
                    default="confirm",
                )
            )
            return
        self._pending_delete_path = node.note.relative_path
        self._pending_delete_neighbor = _neighbor_note_after_delete(
            [row.note.relative_path for row in self._rows],
            node.note.relative_path,
        )
        self.app.push_screen(
            ConfirmActionModal(
                "Delete memory note",
                "Remove this note from the scope? A backup copy will be kept.",
                subject=_build_memory_delete_subject(
                    node.note, child_count=len(children)
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
                default="cancel",
            ),
            self._on_delete_confirmed,
        )

    def action_publish(self) -> None:
        if self._loading or self._write_busy or not self._ring:
            return
        scope = self._current_scope()
        if scope is None:
            return
        self._offer_publish(
            scope,
            memory_publish_subject(scope.display_name),
        )

    def _on_add_draft(self, draft: MemoryNoteFormDraft | None) -> None:
        if draft is None:
            return
        self._submit_memory_write(
            kind="add",
            stem=draft.stem,
            note_type=draft.note_type,
            parent=draft.parent,
            description=draft.description,
        )

    def _on_edit_draft(self, draft: MemoryNoteFormDraft | None) -> None:
        if draft is None:
            return
        node = self._selected_row()
        if node is None:
            return
        self._submit_memory_write(
            kind="edit",
            relative_path=node.note.relative_path,
            note_type=draft.note_type,
            parent=draft.parent,
            description=draft.description,
            preferred_note=node.note.relative_path,
        )

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        path = getattr(self, "_pending_delete_path", None)
        if not path:
            return
        self._submit_memory_write(
            kind="delete",
            relative_path=path,
            preferred_note=getattr(self, "_pending_delete_neighbor", None),
        )

    def _submit_memory_write(
        self,
        *,
        kind: _MemoryWriteKind,
        stem: str = "",
        relative_path: str = "",
        note_type: str = "",
        parent: str = "",
        description: str = "",
        preferred_note: str | None = None,
    ) -> None:
        if self._write_busy or not self._ring:
            return
        scope = (
            self._snapshot.scope
            if self._snapshot is not None
            else self._ring[self._scope_index]
        )
        expected_digest = ""
        if kind in {"edit", "delete"}:
            digest = (
                self._snapshot.digests.get(relative_path) if self._snapshot else None
            )
            if digest is None:
                self.app.notify(
                    "note digest is missing; refresh and retry",
                    severity="error",
                )
                return
            expected_digest = digest.sha256
        submit = getattr(self.app, "_submit_session_worker", None)
        if not callable(submit):
            self.app.notify(
                "Could not write: proc queue unavailable.",
                severity="error",
            )
            return
        self._write_busy = True

        def task() -> TrackedProcResult[_MemoryWritePayload]:
            return _run_memory_panel_write(
                kind=kind,
                scope=scope,
                stem=stem,
                relative_path=relative_path,
                note_type=note_type,
                parent=parent,
                description=description,
                expected_digest=expected_digest,
                preferred_note=preferred_note,
            )

        submitted = submit(
            f"memory-{kind}",
            task,
            on_complete=self._on_memory_write_complete,
            display_name=f"{kind} memory note",
            cl_name=stem or relative_path,
            project_file=scope.content_root,
            dedup_key=f"memory-write:{scope.key}",
            exclusive_scopes=(f"memory-write:{scope.key}",),
        )
        if submitted is None:
            self._write_busy = False

    def _on_memory_write_complete(
        self, completion: TrackedProcCompletion[_MemoryWritePayload]
    ) -> None:
        self._write_busy = False
        payload = completion.payload
        self.app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if payload is not None and payload.error == "conflict":
            if self.is_mounted and self._ring:
                invalidate_memory_scope(self._ring[self._scope_index].key)
                self._start_scope_load()
            return
        if not completion.success or payload is None:
            return
        self._refresh_prompt_memory_catalogs()
        self._mark_scope_unpublished(payload.scope_key)
        if not self.is_mounted or payload.snapshot is None:
            return
        if (
            not self._ring
            or payload.snapshot.scope.key != self._ring[self._scope_index].key
        ):
            return
        if self._scope_worker is not None and not self._scope_worker.is_finished:
            self._scope_worker.cancel()
            self._scope_worker = None
        preferred = payload.preferred_note
        if preferred and self._filter_text:
            visible = {
                note.relative_path
                for note in filter_memory_notes(
                    payload.snapshot.notes,
                    pattern=self._filter_text or None,
                    include_bodies=self._filter_bodies,
                )
            }
            if preferred not in visible:
                filter_input = self._filter_input()
                filter_input.value = ""
                filter_input.display = False
                self._filter_text = ""
        self._loading = False
        self._apply_snapshot(payload.snapshot, preferred_note=preferred)
        scope = payload.snapshot.scope
        subject = memory_publish_subject(
            scope.display_name,
            kind=payload.kind,
            stem=payload.outcome.stem if payload.outcome is not None else None,
        )
        if payload.offer_editor:
            note_path = (
                payload.outcome.relative_path if payload.outcome is not None else ""
            )
            self.call_after_refresh(
                lambda: self._offer_editor_then_publish(
                    scope, subject, note_path=note_path
                )
            )
        else:
            self.call_after_refresh(lambda: self._offer_publish(scope, subject))

    def _offer_editor_then_publish(
        self,
        scope: MemoryScopeRef,
        subject: str,
        *,
        note_path: str,
    ) -> None:
        def after_editor(confirmed: bool | None) -> None:
            if confirmed and self.is_mounted:
                self.action_open_source()
            if self.is_mounted:
                self._offer_publish(scope, subject)

        self.app.push_screen(
            ConfirmActionModal(
                "Write note body",
                "Open the new note in $EDITOR now?",
                subject=note_path or scope.display_name,
                kind=ConfirmKind.NEUTRAL,
                confirm_label="Open editor",
                cancel_label="Skip",
                default="confirm",
            ),
            after_editor,
        )

    def _offer_publish(self, scope: MemoryScopeRef, subject: str) -> None:
        if not self.is_mounted:
            return
        self.app.push_screen(
            MemoryPublishModal(
                scope_display_name=scope.display_name,
                default_subject=subject,
                accent=self._accent,
            ),
            lambda choice: self._on_publish_choice(choice, scope),
        )

    def _on_publish_choice(
        self,
        choice: MemoryPublishChoice | None,
        scope: MemoryScopeRef,
    ) -> None:
        if choice is None:
            return
        self._submit_memory_publish(scope, choice)

    def _submit_memory_publish(
        self, scope: MemoryScopeRef, choice: MemoryPublishChoice
    ) -> None:
        if self._write_busy:
            return
        submit = getattr(self.app, "_submit_session_worker", None)
        if not callable(submit):
            self.app.notify(
                "Could not publish: proc queue unavailable.",
                severity="error",
            )
            return
        self._write_busy = True
        cwd = memory_publish_cwd(scope)
        argv = memory_publish_argv(commit=choice.commit, subject=choice.subject)

        def task() -> TrackedProcResult[_MemoryPublishPayload]:
            return _run_memory_panel_publish(scope=scope, argv=argv, cwd=cwd)

        submitted = submit(
            "memory-publish",
            task,
            on_complete=self._on_memory_publish_complete,
            display_name="publish memory notes",
            cl_name=scope.display_name,
            project_file=str(cwd),
            dedup_key=f"memory-publish:{scope.key}",
            exclusive_scopes=(f"memory-write:{scope.key}",),
        )
        if submitted is None:
            self._write_busy = False

    def _on_memory_publish_complete(
        self, completion: TrackedProcCompletion[_MemoryPublishPayload]
    ) -> None:
        self._write_busy = False
        payload = completion.payload
        self.app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if not completion.success or payload is None:
            return
        self._refresh_prompt_memory_catalogs()
        self._clear_scope_unpublished(payload.scope_key)
        if (
            self.is_mounted
            and self._ring
            and self._ring[self._scope_index].key == payload.scope_key
        ):
            invalidate_memory_scope(payload.scope_key)
            self._start_scope_load()

    def _current_scope(self) -> MemoryScopeRef | None:
        if self._snapshot is not None:
            return self._snapshot.scope
        if self._ring:
            return self._ring[self._scope_index]
        return None

    def _refresh_prompt_memory_catalogs(self) -> None:
        refresh = getattr(self.app, "_schedule_prompt_catalog_rebuild", None)
        if callable(refresh):
            refresh(reason="memory-panel-write", force=True)


def _run_memory_panel_write(
    *,
    kind: _MemoryWriteKind,
    scope: MemoryScopeRef,
    stem: str,
    relative_path: str,
    note_type: str,
    parent: str,
    description: str,
    expected_digest: str,
    preferred_note: str | None,
) -> TrackedProcResult[_MemoryWritePayload]:
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
            payload=_MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="validation"
            ),
        )
    except MemoryConflictError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=_MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="conflict"
            ),
        )
    except MemoryGeneratedNoteError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=_MemoryWritePayload(
                kind=kind, scope_key=scope.key, error="generated"
            ),
        )
    except MemoryMutationError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=_MemoryWritePayload(kind=kind, scope_key=scope.key, error="other"),
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
        payload=_MemoryWritePayload(
            kind=kind,
            scope_key=scope.key,
            outcome=outcome,
            snapshot=snapshot,
            preferred_note=preferred,
            offer_editor=kind == "add",
        ),
    )


def _run_memory_panel_publish(
    *,
    scope: MemoryScopeRef,
    argv: list[str],
    cwd: Any,
) -> TrackedProcResult[_MemoryPublishPayload]:
    """Run ``sase memory init`` off the event loop and return its outcome."""
    from subprocess import TimeoutExpired

    try:
        completed = run_noninteractive(argv, cwd=cwd)
    except TimeoutExpired:
        return TrackedProcResult(
            False,
            format_memory_publish_failure(None, timeout=True),
            payload=_MemoryPublishPayload(scope_key=scope.key, error="timeout"),
        )
    except OSError as exc:
        return TrackedProcResult(
            False,
            f"could not run sase memory init: {exc}",
            payload=_MemoryPublishPayload(scope_key=scope.key, error="other"),
        )
    if completed.returncode != 0:
        return TrackedProcResult(
            False,
            format_memory_publish_failure(completed),
            payload=_MemoryPublishPayload(scope_key=scope.key, error="command"),
        )
    return TrackedProcResult(
        True,
        f"Published memory notes for {scope.display_name}.",
        payload=_MemoryPublishPayload(scope_key=scope.key),
    )


def _success_message(
    kind: _MemoryWriteKind,
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


__all__ = ["MemoryPanelActionsMixin"]
