"""Add/delete write surfaces for the Glossary panel.

Both writes go through the app's session-worker queue (the current tracked-proc
API), call the shared glossary mutation engine off the event loop, and apply
reselect / toast / commit-offer effects back on the UI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.glossary_panel_catalog import (
    GlossaryProjectRef,
    GlossaryProjectSnapshot,
    invalidate_glossary_project,
    load_glossary_project_snapshot,
)
from sase.glossary.cli_common import GlossaryCliError
from sase.glossary.mutation import (
    GlossaryConflictError,
    GlossaryMutationError,
    GlossaryMutationOutcome,
    GlossaryValidationError,
    add_glossary_term,
    delete_glossary_term,
)
from sase.glossary.resolution import GlossaryLookupError
from sase.glossary.text_filter import filter_glossary_entries

from .config_commit import (
    ConfigCommitOffer,
    build_config_commit_offer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .glossary_panel_add import GlossaryAddDraft, GlossaryTermAddModal
from .glossary_panel_delete import (
    build_glossary_delete_subject,
    neighbor_term_after_delete,
)
from .glossary_panel_rendering import sorted_glossary_entries
from .glossary_preview_render import glossary_source_path

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
    from textual.worker import Worker

    from sase.core.glossary_facade import GlossaryEntry
else:
    _MixinBase = object

_GlossaryWriteKind = Literal["add", "delete"]


@dataclass(frozen=True, slots=True)
class _GlossaryWritePayload:
    kind: _GlossaryWriteKind
    error: str | None = None
    outcome: GlossaryMutationOutcome | None = None
    snapshot: GlossaryProjectSnapshot | None = None
    offer: ConfigCommitOffer | None = None
    preferred_term: str | None = None


class GlossaryPanelActionsMixin(_MixinBase):
    """Add-form and delete-confirmation actions for :class:`GlossaryPanel`."""

    if TYPE_CHECKING:
        _loading: bool
        _write_busy: bool
        _accent: str
        _filter_text: str
        _filter_definitions: bool
        _current_term: str | None
        _project_index: int
        _ring: tuple[GlossaryProjectRef, ...]
        _snapshot: GlossaryProjectSnapshot | None
        _all_entries: tuple[GlossaryEntry, ...]
        _entries: tuple[GlossaryEntry, ...]
        _project_worker: Worker[GlossaryProjectSnapshot] | None
        _pending_delete_term: str | None
        _pending_delete_neighbor: str | None
        is_mounted: bool
        app: Any

        def _apply_snapshot(
            self,
            snapshot: GlossaryProjectSnapshot | None,
            *,
            preferred_term: str | None,
        ) -> None: ...

        def _start_project_load(self) -> None: ...

        def _selected_entry(self) -> GlossaryEntry | None: ...

        def _filter_input(self) -> Any: ...

    def action_add_term(self) -> None:
        if self._loading or self._write_busy or not self._ring:
            return
        project_name = (
            self._snapshot.project.display_name
            if self._snapshot is not None
            else self._ring[self._project_index].display_name
        )
        self.app.push_screen(
            GlossaryTermAddModal(
                existing_entries=self._all_entries,
                project_display_name=project_name,
                accent=self._accent,
            ),
            self._on_add_draft,
        )

    def action_delete_term(self) -> None:
        if self._loading or self._write_busy:
            return
        entry = self._selected_entry()
        snapshot = self._snapshot
        if entry is None or snapshot is None:
            return
        referenced_by = tuple(snapshot.reverse_references.get(entry.index, ()))
        config_path = (
            glossary_source_path(snapshot.catalog, entry)
            if snapshot.catalog is not None
            else None
        )
        self._pending_delete_term = entry.term
        self._pending_delete_neighbor = neighbor_term_after_delete(
            [item.term for item in self._entries],
            entry.term,
        )
        self.app.push_screen(
            ConfirmActionModal(
                "Delete glossary term",
                "Remove this term from the project glossary? This cannot be undone.",
                subject=build_glossary_delete_subject(
                    term=entry.term,
                    aliases=entry.configured_aliases,
                    definition=entry.definition,
                    config_path=config_path,
                    referenced_by=referenced_by,
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
                default="cancel",
            ),
            self._on_delete_confirmed,
        )

    def _on_add_draft(self, draft: GlossaryAddDraft | None) -> None:
        if draft is None:
            return
        self._submit_glossary_write(
            kind="add",
            term=draft.term,
            definition=draft.definition,
            aliases=draft.aliases,
            preferred_term=draft.term,
        )

    def _on_delete_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        term = getattr(self, "_pending_delete_term", None)
        if not term:
            return
        self._submit_glossary_write(
            kind="delete",
            term=term,
            preferred_term=getattr(self, "_pending_delete_neighbor", None),
        )

    def _submit_glossary_write(
        self,
        *,
        kind: _GlossaryWriteKind,
        term: str,
        definition: str = "",
        aliases: tuple[str, ...] = (),
        preferred_term: str | None = None,
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
        self._write_busy = True

        def task() -> TrackedProcResult[_GlossaryWritePayload]:
            return _run_glossary_panel_write(
                kind=kind,
                project=project,
                term=term,
                definition=definition,
                aliases=aliases,
                preferred_term=preferred_term,
            )

        submitted = submit(
            f"glossary-{kind}",
            task,
            on_complete=self._on_glossary_write_complete,
            display_name=f"{kind} glossary term",
            cl_name=term,
            project_file=project.workspace_dir,
            dedup_key=f"glossary-write:{project.key}",
            exclusive_scopes=(f"glossary-write:{project.key}",),
        )
        if submitted is None:
            self._write_busy = False

    def _on_glossary_write_complete(
        self, completion: TrackedProcCompletion[_GlossaryWritePayload]
    ) -> None:
        self._write_busy = False
        payload = completion.payload
        self.app.notify(
            completion.message,
            severity="information" if completion.success else "error",
        )
        if payload is not None and payload.error == "conflict":
            if self.is_mounted and self._ring:
                invalidate_glossary_project(self._ring[self._project_index].key)
                self._start_project_load()
            return
        if not completion.success or payload is None:
            return
        invalidate_prompt = getattr(
            self.app, "_invalidate_prompt_glossary_catalogs", None
        )
        if callable(invalidate_prompt):
            invalidate_prompt(reason="glossary-panel-write")
        if payload.offer is not None:
            push_config_commit_prompt(
                self.app,
                payload.offer,
                message="Commit and push your glossary change?",
                on_confirm=lambda offer: submit_config_commit_task(
                    self.app,
                    offer,
                    display_name=f"commit glossary {offer.rel_path}",
                ),
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
        preferred = payload.preferred_term
        if preferred and self._filter_text:
            visible = {
                entry.term
                for entry in filter_glossary_entries(
                    sorted_glossary_entries(payload.snapshot.catalog),
                    pattern=self._filter_text or None,
                    include_definitions=self._filter_definitions,
                )
            }
            if preferred not in visible:
                filter_input = self._filter_input()
                filter_input.value = ""
                filter_input.display = False
                self._filter_text = ""
        self._loading = False
        self._apply_snapshot(payload.snapshot, preferred_term=preferred)


def _run_glossary_panel_write(
    *,
    kind: _GlossaryWriteKind,
    project: GlossaryProjectRef,
    term: str,
    definition: str,
    aliases: tuple[str, ...],
    preferred_term: str | None,
) -> TrackedProcResult[_GlossaryWritePayload]:
    """Apply one add/delete and reload that project's snapshot.

    Called only from a session worker: config writes, catalog reload, and the
    git-status probe for a commit offer must stay off the event loop.
    """
    try:
        if kind == "add":
            outcome = add_glossary_term(project.key, term, definition, aliases)
        else:
            outcome = delete_glossary_term(project.key, term)
    except GlossaryValidationError as exc:
        return TrackedProcResult(
            False,
            _validation_message(exc),
            payload=_GlossaryWritePayload(kind=kind, error="validation"),
        )
    except GlossaryConflictError as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=_GlossaryWritePayload(kind=kind, error="conflict"),
        )
    except (
        GlossaryMutationError,
        GlossaryCliError,
        GlossaryLookupError,
    ) as exc:
        return TrackedProcResult(
            False,
            str(exc),
            payload=_GlossaryWritePayload(kind=kind, error="other"),
        )
    invalidate_glossary_project(project.key)
    snapshot = load_glossary_project_snapshot(project)
    offer = build_config_commit_offer(
        outcome.config_path,
        subject=(
            f"Add glossary term {outcome.term}"
            if kind == "add"
            else f"Delete glossary term {outcome.term}"
        ),
    )
    return TrackedProcResult(
        True,
        _success_message(kind, outcome),
        payload=_GlossaryWritePayload(
            kind=kind,
            outcome=outcome,
            snapshot=snapshot,
            offer=offer,
            preferred_term=preferred_term if kind == "delete" else outcome.term,
        ),
    )


def _success_message(kind: _GlossaryWriteKind, outcome: GlossaryMutationOutcome) -> str:
    project = outcome.project_name
    if kind == "add":
        return (
            f'Added "{outcome.term}" to {project}. '
            "Run sase memory init to publish it to agents."
        )
    return (
        f'Deleted "{outcome.term}" from {project}. '
        f"Restore with: {outcome.restore_command}  "
        "Run sase memory init to publish it to agents."
    )


def _validation_message(exc: GlossaryValidationError) -> str:
    if not exc.diagnostics:
        return str(exc)
    first = exc.diagnostics[0]
    return f"{first.code}: {first.message}"


__all__ = ["GlossaryPanelActionsMixin"]
