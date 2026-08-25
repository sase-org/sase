"""Add/edit/delete write surfaces for the Memory panel.

Writes go through the app's session-worker queue, call the shared memory
mutation engine off the event loop, and apply reselect / toast /
unpublished / publish-offer effects back on the UI thread. Publish lives
in :mod:`sase.ace.tui.modals.memory_panel_publish_actions`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.memory_panel_catalog import (
    MemoryScopeRef,
    invalidate_memory_scope,
    memory_rail_node_label,
    memory_rail_node_relations,
)
from sase.memory.text_filter import filter_memory_notes

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .memory_panel_add import MemoryNoteFormDraft, MemoryNoteFormModal
from .memory_panel_delete import (
    build_child_blocked_delete_message,
    build_memory_delete_subject,
    build_memory_strand_delete_subject,
    children_of,
    neighbor_note_after_delete,
)
from .memory_panel_publish import memory_publish_subject
from .memory_panel_publish_actions import MemoryPanelPublishActionsMixin
from .memory_panel_strand_add import MemoryStrandFormDraft, MemoryStrandFormModal
from .memory_panel_write import (
    MemoryWriteKind,
    MemoryWritePayload,
    run_memory_panel_write,
)

if TYPE_CHECKING:
    from textual.worker import Worker

    from sase.ace.tui.memory_panel_catalog import MemoryRailNode, MemoryScopeSnapshot


class MemoryPanelActionsMixin(MemoryPanelPublishActionsMixin):
    """Add/edit forms and delete confirmation for MemoryPanel."""

    if TYPE_CHECKING:
        _accent: str
        _current_note: str | None
        _expanded_webs: set[str]
        _filter_bodies: bool
        _filter_text: str
        _loading: bool
        _pending_delete_neighbor: str | None
        _pending_delete_path: str | None
        _pending_delete_strand: tuple[str, str] | None
        _ring: tuple[MemoryScopeRef, ...]
        _rows: tuple[MemoryRailNode, ...]
        _scope_index: int
        _scope_worker: Worker[MemoryScopeSnapshot] | None
        _snapshot: MemoryScopeSnapshot | None
        _unpublished_scopes: set[str]
        _write_busy: bool
        _closed: bool
        is_mounted: bool
        app: Any

        def _apply_snapshot(
            self,
            snapshot: MemoryScopeSnapshot | None,
            *,
            preferred_note: str | None,
        ) -> None: ...

        def _filter_input(self) -> Any: ...

        def _mark_scope_unpublished(self, scope_key: str | None = None) -> None: ...

        def _selected_row(self) -> MemoryRailNode | None: ...

        def _start_scope_load(self) -> None: ...

    def action_add_note(self) -> None:
        if self._loading or self._write_busy or not self._ring:
            return
        scope = self._current_scope()
        if scope is None:
            return
        node = self._selected_row()
        if node is not None and node.is_web and node.web is not None:
            self.app.push_screen(
                MemoryStrandFormModal(
                    web=node.web,
                    scope_display_name=scope.display_name,
                    accent=self._accent,
                ),
                self._on_add_strand_draft,
            )
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
        if node.is_strand:
            self.app.notify(
                "memory strands are edited from their source file",
                severity="warning",
            )
            return
        if node.note.relative_path in snapshot.generated_paths:
            self.app.notify(
                f"generated memory note is read-only: {node.note.relative_path}",
                severity="warning",
            )
            return
        note = node.note
        note_type = note.type if note.type in {"core", "reference"} else "reference"
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
        if node.is_strand:
            self._confirm_strand_delete(node, snapshot)
            return
        if node.note.relative_path in snapshot.generated_paths:
            self.app.notify(
                f"generated memory note is read-only: {node.note.relative_path}",
                severity="warning",
            )
            return
        children = children_of(snapshot.notes, node.note.relative_path)
        if children:
            self.app.push_screen(
                ConfirmActionModal(
                    "Cannot delete memory note",
                    build_child_blocked_delete_message(children),
                    subject="\n".join(child.relative_path for child in children),
                    kind=ConfirmKind.NEUTRAL,
                    confirm_label="OK",
                    cancel_label="Close",
                    default="confirm",
                )
            )
            return
        self._pending_delete_strand = None
        self._pending_delete_path = node.note.relative_path
        self._pending_delete_neighbor = neighbor_note_after_delete(
            [row.note.relative_path for row in self._rows],
            node.note.relative_path,
        )
        self.app.push_screen(
            ConfirmActionModal(
                "Delete memory note",
                "Remove this note from the scope? A backup copy will be kept.",
                subject=build_memory_delete_subject(
                    node.note, child_count=len(children)
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
                default="cancel",
            ),
            self._on_delete_confirmed,
        )

    def _confirm_strand_delete(
        self, node: MemoryRailNode, snapshot: MemoryScopeSnapshot
    ) -> None:
        web = node.web
        strand = node.strand
        if web is None or strand is None:
            return
        _outbound, inbound = memory_rail_node_relations(snapshot, node)
        referenced_by = tuple(
            memory_rail_node_label(snapshot, item) for item in inbound
        )
        self._pending_delete_strand = (web.slug, strand.slug)
        self._pending_delete_path = node.note.relative_path
        self._pending_delete_neighbor = neighbor_note_after_delete(
            [row.note.relative_path for row in self._rows],
            node.note.relative_path,
        )
        self.app.push_screen(
            ConfirmActionModal(
                "Delete memory strand",
                "Remove this strand from the web? A backup copy will be kept.",
                subject=build_memory_strand_delete_subject(
                    web, strand, referenced_by=referenced_by
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
                default="cancel",
            ),
            self._on_delete_confirmed,
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

    def _on_add_strand_draft(self, draft: MemoryStrandFormDraft | None) -> None:
        if draft is None:
            return
        self._submit_memory_write(
            kind="add_strand",
            web_slug=draft.web_slug,
            slug=draft.slug,
            keyword=draft.keyword,
            aliases=draft.aliases,
            summary=draft.summary,
            body=draft.body,
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
        strand_pending = getattr(self, "_pending_delete_strand", None)
        if strand_pending is not None:
            web_slug, slug = strand_pending
            self._pending_delete_strand = None
            self._submit_memory_write(
                kind="delete_strand",
                relative_path=f"{web_slug}:{slug}",
                web_slug=web_slug,
                slug=slug,
                preferred_note=getattr(self, "_pending_delete_neighbor", None),
            )
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
        kind: MemoryWriteKind,
        stem: str = "",
        relative_path: str = "",
        note_type: str = "",
        parent: str = "",
        description: str = "",
        preferred_note: str | None = None,
        web_slug: str = "",
        slug: str = "",
        keyword: str | None = None,
        aliases: Sequence[str] = (),
        summary: str | None = None,
        body: str = "",
    ) -> None:
        if self._write_busy or not self._ring:
            return
        scope = (
            self._snapshot.scope
            if self._snapshot is not None
            else self._ring[self._scope_index]
        )
        expected_digest = ""
        if kind in {"edit", "delete", "delete_strand"}:
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

        def task() -> TrackedProcResult[MemoryWritePayload]:
            return run_memory_panel_write(
                kind=kind,
                scope=scope,
                stem=stem,
                relative_path=relative_path,
                note_type=note_type,
                parent=parent,
                description=description,
                expected_digest=expected_digest,
                preferred_note=preferred_note,
                web_slug=web_slug,
                slug=slug,
                keyword=keyword,
                aliases=aliases,
                summary=summary,
                body=body,
            )

        submitted = submit(
            f"memory-{kind}",
            task,
            on_complete=self._on_memory_write_complete,
            display_name=f"{kind} memory note",
            cl_name=stem or slug or relative_path,
            project_file=scope.content_root,
            dedup_key=f"memory-write:{scope.key}",
            exclusive_scopes=(f"memory-write:{scope.key}",),
        )
        if submitted is None:
            self._write_busy = False

    def _on_memory_write_complete(
        self, completion: TrackedProcCompletion[MemoryWritePayload]
    ) -> None:
        self._write_busy = False
        payload = completion.payload
        self.app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if payload is not None and payload.error == "conflict":
            if self.is_mounted and not self._closed and self._ring:
                invalidate_memory_scope(self._ring[self._scope_index].key)
                self._start_scope_load()
            return
        if not completion.success or payload is None:
            return
        self._refresh_prompt_memory_catalogs()
        self._mark_scope_unpublished(payload.scope_key)
        if not self.is_mounted or self._closed or payload.snapshot is None:
            return
        if (
            not self._ring
            or payload.snapshot.scope.key != self._ring[self._scope_index].key
        ):
            return
        if self._scope_worker is not None and not self._scope_worker.is_finished:
            self._scope_worker.cancel()
            self._scope_worker = None
        if payload.strand_outcome is not None:
            self._expanded_webs.add(payload.strand_outcome.web_slug)
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
        stem = payload.outcome.stem if payload.outcome is not None else None
        if stem is None and payload.strand_outcome is not None:
            stem = payload.strand_outcome.keyword
        subject = memory_publish_subject(
            scope.display_name,
            kind=payload.kind,
            stem=stem,
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


__all__ = ["MemoryPanelActionsMixin"]
