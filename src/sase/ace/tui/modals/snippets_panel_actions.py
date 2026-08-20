"""Add/edit/delete write surfaces for the Snippets panel.

Writes go through the app's session-worker queue, call the shared snippet
mutation engine off the event loop, and apply reselect / toast /
session-overlay / post-write effects back on the UI thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.snippets_panel_catalog import (
    SnippetProjectRef,
    SnippetProjectSnapshot,
    invalidate_snippet_project,
)
from sase.snippet.text_filter import filter_snippet_entries

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .snippets_panel_add import SnippetFormDraft, SnippetFormModal
from .snippets_panel_delete import (
    build_snippet_delete_subject,
    neighbor_trigger_after_delete,
    snippet_entry_is_mutable,
)
from .snippets_panel_rendering import sorted_snippet_entries
from .snippets_panel_write import (
    SnippetWriteKind,
    SnippetWritePayload,
    run_snippets_panel_write,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.worker import Worker

    from sase.snippet.models import SnippetCatalog, SnippetEntry
else:
    _MixinBase = object


class SnippetsPanelActionsMixin(_MixinBase):
    """Add/edit forms and delete confirmation for :class:`SnippetsPanel`."""

    if TYPE_CHECKING:
        _accent: str
        _all_entries: tuple[SnippetEntry, ...]
        _current_trigger: str | None
        _entries: tuple[SnippetEntry, ...]
        _filter_bodies: bool
        _filter_text: str
        _loading: bool
        _pending_delete_neighbor: str | None
        _pending_delete_trigger: str | None
        _pending_draft: SnippetFormDraft | None
        _project_index: int
        _project_worker: Worker[SnippetProjectSnapshot] | None
        _ring: tuple[SnippetProjectRef, ...]
        _snapshot: SnippetProjectSnapshot | None
        _write_busy: bool
        is_mounted: bool
        app: Any

        def _apply_snapshot(
            self,
            snapshot: SnippetProjectSnapshot | None,
            *,
            preferred_trigger: str | None,
        ) -> None: ...

        def _filter_input(self) -> Any: ...

        def _selected_entry(self) -> SnippetEntry | None: ...

        def _start_project_load(self) -> None: ...

        def action_open_source(self) -> None: ...

    def action_add_snippet(self) -> None:
        if self._loading or self._write_busy or not self._ring:
            return
        self._open_form(mode="add")

    def action_edit_snippet(self) -> None:
        if self._loading or self._write_busy:
            return
        entry = self._selected_entry()
        if entry is None:
            return
        if not snippet_entry_is_mutable(entry):
            if entry.origin.kind == "xprompt":
                self.action_open_source()
                return
            source = entry.origin.display_path or entry.origin.kind
            self.app.notify(
                f"cannot edit {entry.trigger}: definition comes from {source}",
                severity="warning",
            )
            return
        self._open_form(
            mode="edit",
            initial_trigger=entry.trigger,
            initial_template=entry.raw_template,
            default_destination_path=entry.origin.path,
        )

    def action_delete_snippet(self) -> None:
        if self._loading or self._write_busy:
            return
        entry = self._selected_entry()
        if entry is None:
            return
        if not snippet_entry_is_mutable(entry):
            source = entry.origin.display_path or entry.origin.kind
            self.app.notify(
                f"cannot delete {entry.trigger}: definition comes from {source}",
                severity="warning",
            )
            return
        self._pending_delete_trigger = entry.trigger
        self._pending_delete_neighbor = neighbor_trigger_after_delete(
            [item.trigger for item in self._entries],
            entry.trigger,
        )
        self.app.push_screen(
            ConfirmActionModal(
                "Delete snippet",
                "Remove this snippet from the writable config file? "
                "This cannot be undone.",
                subject=build_snippet_delete_subject(entry),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
                default="cancel",
            ),
            self._on_delete_confirmed,
        )

    def _open_form(
        self,
        *,
        mode: str,
        initial_trigger: str = "",
        initial_template: str = "",
        default_destination_path: str | None = None,
        draft: SnippetFormDraft | None = None,
    ) -> None:
        snapshot = self._snapshot
        catalog: SnippetCatalog | None = (
            snapshot.catalog if snapshot is not None else None
        )
        destinations = () if snapshot is None else snapshot.destinations
        project_name = (
            snapshot.project.display_name
            if snapshot is not None
            else self._ring[self._project_index].display_name
        )
        default_path = default_destination_path
        if default_path is None and snapshot is not None:
            default_path = snapshot.default_destination_path
        if draft is not None:
            initial_trigger = draft.trigger
            initial_template = draft.template
            default_path = draft.target
            mode = draft.mode if draft.mode in {"add", "edit"} else mode
        self.app.push_screen(
            SnippetFormModal(
                mode=mode,  # type: ignore[arg-type]
                catalog=catalog,
                destinations=destinations,
                default_destination_path=default_path,
                project_display_name=project_name,
                initial_trigger=initial_trigger,
                initial_template=initial_template,
                accent=self._accent,
            ),
            self._on_form_draft,
        )

    def _on_form_draft(self, draft: SnippetFormDraft | None) -> None:
        if draft is None:
            self._pending_draft = None
            return
        self._pending_draft = draft
        self._submit_snippet_write(
            kind=draft.mode,
            trigger=draft.trigger,
            template=draft.template,
            target=draft.target,
            expected_digest=draft.expected_digest,
            force=draft.force,
            preferred_trigger=draft.trigger,
        )

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        trigger = getattr(self, "_pending_delete_trigger", None)
        if not trigger:
            return
        entry = next(
            (item for item in self._all_entries if item.trigger == trigger), None
        )
        target = None if entry is None else entry.origin.path
        digest = _digest_for_path(self._snapshot, target)
        self._submit_snippet_write(
            kind="delete",
            trigger=trigger,
            target=target,
            expected_digest=digest,
            preferred_trigger=getattr(self, "_pending_delete_neighbor", None),
        )

    def _submit_snippet_write(
        self,
        *,
        kind: SnippetWriteKind,
        trigger: str,
        template: str = "",
        target: str | None = None,
        expected_digest: str | None = None,
        force: bool = False,
        preferred_trigger: str | None = None,
    ) -> None:
        if self._write_busy or not self._ring:
            return
        project = (
            self._snapshot.project
            if self._snapshot is not None
            else self._ring[self._project_index]
        )
        submit = getattr(self.app, "_submit_session_worker", None)
        if not callable(submit):
            self.app.notify(
                "Could not write: proc queue unavailable.",
                severity="error",
            )
            return
        pending = dict(getattr(self.app, "_pending_snippet_saves", {}) or {})
        exclusive = f"snippet-write:{project.key}:{target or 'default'}"
        self._write_busy = True

        def task() -> TrackedProcResult[SnippetWritePayload]:
            return run_snippets_panel_write(
                kind=kind,
                project=project,
                trigger=trigger,
                template=template,
                target=target,
                expected_digest=expected_digest,
                force=force,
                preferred_trigger=preferred_trigger,
                pending_saves=pending,
            )

        submitted = submit(
            f"snippet-{kind}",
            task,
            on_complete=self._on_snippet_write_complete,
            display_name=f"{kind} snippet",
            cl_name=trigger,
            project_file=project.workspace_dir,
            dedup_key=exclusive,
            exclusive_scopes=(exclusive,),
        )
        if submitted is None:
            self._write_busy = False

    def _on_snippet_write_complete(
        self, completion: TrackedProcCompletion[SnippetWritePayload]
    ) -> None:
        self._write_busy = False
        payload = completion.payload
        self.app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if payload is not None and payload.error == "conflict":
            self._on_write_conflict(payload)
            return
        if not completion.success or payload is None:
            return
        self._pending_draft = None
        self._publish_session_overlay(payload)
        if payload.offers and payload.write_target is not None:
            push = getattr(self.app, "_push_post_write_actions", None)
            if callable(push):
                push(
                    payload.offers,
                    target=payload.write_target,
                    noun="snippet",
                    refresh_config_on_success=True,
                )
        if not self.is_mounted or payload.snapshot is None:
            return
        if (
            not self._ring
            or payload.snapshot.project.key != self._ring[self._project_index].key
        ):
            return
        if self._project_worker is not None and not self._project_worker.is_finished:
            self._project_worker.cancel()
            self._project_worker = None
        preferred = payload.preferred_trigger
        if preferred and self._filter_text:
            visible = {
                entry.trigger
                for entry in filter_snippet_entries(
                    sorted_snippet_entries(payload.snapshot.catalog),
                    pattern=self._filter_text or None,
                    include_bodies=self._filter_bodies,
                )
            }
            if preferred not in visible:
                filter_input = self._filter_input()
                filter_input.value = ""
                filter_input.display = False
                self._filter_text = ""
                self.app.notify(f"Cleared filter to show {preferred}.")
        self._loading = False
        self._apply_snapshot(payload.snapshot, preferred_trigger=preferred)

    def _on_write_conflict(self, payload: SnippetWritePayload) -> None:
        draft = self._pending_draft
        if draft is None and payload.draft_trigger:
            mode = (
                payload.draft_mode if payload.draft_mode in {"add", "edit"} else "add"
            )
            draft = SnippetFormDraft(
                trigger=payload.draft_trigger,
                template=payload.draft_template or "",
                target=payload.draft_target,
                expected_digest=payload.draft_digest,
                force=payload.draft_force,
                mode=mode,  # type: ignore[arg-type]
            )
        if payload.kind == "delete":
            if self.is_mounted and self._ring:
                invalidate_snippet_project(self._ring[self._project_index].key)
                self._start_project_load()
            return
        if draft is None:
            return

        def _after_reload(confirmed: bool | None) -> None:
            if confirmed and self.is_mounted and self._ring:
                invalidate_snippet_project(self._ring[self._project_index].key)
                self._start_project_load()
            if draft is not None:
                self._open_form(mode=draft.mode, draft=draft)

        self.app.push_screen(
            ConfirmActionModal(
                "Snippet config changed",
                "Reload the destination and keep your draft?",
                subject=_completion_path(payload),
                kind=ConfirmKind.NEUTRAL,
                confirm_label="Reload",
                cancel_label="Keep draft",
                default="confirm",
            ),
            _after_reload,
        )

    def _publish_session_overlay(self, payload: SnippetWritePayload) -> None:
        if payload.pending_saves is not None:
            self.app._pending_snippet_saves = dict(payload.pending_saves)
        if payload.composed_snippets is not None:
            self.app._snippets_cache = dict(payload.composed_snippets)
        surfaces = getattr(self.app, "_refresh_visible_prompt_catalog_surfaces", None)
        if callable(surfaces):
            surfaces()
        refresh = getattr(self.app, "_request_prompt_catalog_config_refresh", None)
        if callable(refresh):
            refresh(reason="snippets-panel-write")


def _digest_for_path(
    snapshot: SnippetProjectSnapshot | None, path: str | None
) -> str | None:
    if snapshot is None or not path:
        return None
    for destination in snapshot.destinations:
        if destination.path == path:
            return destination.digest
    return None


def _completion_path(payload: SnippetWritePayload) -> str:
    if payload.write_target is not None:
        return str(payload.write_target.write_path)
    if payload.draft_target:
        return payload.draft_target
    return ""


__all__ = ["SnippetsPanelActionsMixin"]
