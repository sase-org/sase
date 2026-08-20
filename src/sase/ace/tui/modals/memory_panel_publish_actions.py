"""Publish confirmation and ``sase memory init`` submission for the Memory panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.memory_panel_catalog import MemoryScopeRef, invalidate_memory_scope

from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .memory_panel_publish import (
    MemoryPublishChoice,
    MemoryPublishModal,
    memory_publish_argv,
    memory_publish_cwd,
    memory_publish_subject,
)
from .memory_panel_write import MemoryPublishPayload, run_memory_panel_publish

if TYPE_CHECKING:
    from textual.widget import Widget as _MixinBase

    from sase.ace.tui.memory_panel_catalog import MemoryScopeSnapshot
else:
    _MixinBase = object


class MemoryPanelPublishActionsMixin(_MixinBase):
    """On-demand and post-write publish offers for :class:`MemoryPanel`."""

    if TYPE_CHECKING:
        _accent: str
        _loading: bool
        _ring: tuple[MemoryScopeRef, ...]
        _scope_index: int
        _snapshot: MemoryScopeSnapshot | None
        _write_busy: bool
        _closed: bool
        is_mounted: bool
        app: Any

        def _clear_scope_unpublished(self, scope_key: str) -> None: ...

        def _current_scope(self) -> MemoryScopeRef | None: ...

        def _refresh_prompt_memory_catalogs(self) -> None: ...

        def _start_scope_load(self) -> None: ...

        def action_open_source(self) -> None: ...

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

    def _offer_editor_then_publish(
        self,
        scope: MemoryScopeRef,
        subject: str,
        *,
        note_path: str,
    ) -> None:
        def after_editor(confirmed: bool | None) -> None:
            if confirmed and self.is_mounted and not self._closed:
                self.action_open_source()
            if self.is_mounted and not self._closed:
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
        if not self.is_mounted or self._closed:
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

        def task() -> TrackedProcResult[MemoryPublishPayload]:
            return run_memory_panel_publish(scope=scope, argv=argv, cwd=cwd)

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
        self, completion: TrackedProcCompletion[MemoryPublishPayload]
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
            and not self._closed
            and self._ring
            and self._ring[self._scope_index].key == payload.scope_key
        ):
            invalidate_memory_scope(payload.scope_key)
            self._start_scope_load()


__all__ = ["MemoryPanelPublishActionsMixin"]
