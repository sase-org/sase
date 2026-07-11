"""Persistent alias-edit and commit workflow for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.config import ConfigEditOp
from sase.llm_provider import AliasView

from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from .models_panel_edit import AliasEditPreviewModal
from .models_panel_edit_helpers import (
    AliasCommitOffer,
    AliasEditOutcome,
    alias_model_edit_path,
    alias_reset_path,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelAliasEditMixin(_MixinBase):
    """Edit persistent alias values and optionally commit the resulting file."""

    if TYPE_CHECKING:
        _pending_edit_view: AliasView | None

        def _selected_alias(self) -> AliasView | None: ...

        def _refresh_rows(self, *, keep: str | None = None) -> None: ...

        def _build_alias_commit_offer(
            self, path: str, *, op: str, alias: str
        ) -> AliasCommitOffer | None: ...

    def action_edit(self) -> None:
        view = self._selected_alias()
        if view is None:
            return
        self._pending_edit_view = view
        self.app.push_screen(
            ModelPickerModal(
                title=f"Edit Model — @{view.name}",
                include_default_option=False,
            ),
            callback=self._on_edit_model_picked,
        )

    def action_reset(self) -> None:
        view = self._selected_alias()
        if view is None:
            return
        if not view.configured:
            self.notify(
                f"@{view.name} has no configured value to reset",
                severity="warning",
            )
            return
        self._open_alias_preview(
            view.name,
            ConfigEditOp.unset(),
            path=alias_reset_path(
                view.name,
                kind=view.kind,
                configured_source=view.configured_source,
            ),
            reset_deletes_alias=(
                view.kind == "user" and view.configured_source == "custom"
            ),
        )

    def _on_edit_model_picked(self, result: str | None) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Alias Value",
                    hint="Format: provider/model, model, or @alias",
                    placeholder="e.g. claude/opus  or  @default",
                ),
                callback=self._on_edit_custom_picked,
            )
            return
        self._open_model_edit_preview(view, result)

    def _on_edit_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        self._open_model_edit_preview(view, result)

    def _open_model_edit_preview(self, view: AliasView, model: str) -> None:
        self._open_alias_preview(
            view.name,
            ConfigEditOp.set_value(model),
            path=alias_model_edit_path(
                view.name,
                kind=view.kind,
                configured_source=view.configured_source,
            ),
        )

    def _open_alias_preview(
        self,
        alias: str,
        op: ConfigEditOp,
        *,
        path: str | None = None,
        action_label: str | None = None,
        reset_deletes_alias: bool = False,
    ) -> None:
        self.app.push_screen(
            AliasEditPreviewModal(
                alias,
                op,
                path=path,
                action_label=action_label,
                reset_deletes_alias=reset_deletes_alias,
            ),
            callback=self._on_alias_edited,
        )

    def _on_alias_edited(self, outcome: AliasEditOutcome | None) -> None:
        if outcome is None:
            return
        verb = "Reset" if outcome.applied.op == "unset" else "Updated"
        self.notify(f"{verb} @{outcome.alias}")
        # Persistent edits do not touch temporary overrides. Refresh the rows
        # so the configured/effective columns reflect the new value.
        self._refresh_rows(keep=outcome.alias)
        self._offer_commit_push(outcome)

    def _offer_commit_push(self, outcome: AliasEditOutcome) -> None:
        offer = self._build_alias_commit_offer(
            outcome.applied.path,
            op=outcome.applied.op,
            alias=outcome.alias,
        )
        if offer is None:
            return
        from .confirm_action_modal import ConfirmActionModal

        def _on_answer(confirmed: bool | None) -> None:
            if confirmed:
                self._submit_commit_task(offer)

        self.app.push_screen(
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your model-alias change?",
                subject=offer.rel_path,
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            ),
            _on_answer,
        )

    def _submit_commit_task(self, offer: AliasCommitOffer) -> None:
        from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
            GitCommitPushResult,
            git_index_lock_retry_message,
            run_git_commit_push_sync,
        )
        from sase.ace.tui.actions.task_actions import (
            TrackedTaskCompletion,
            TrackedTaskResult,
        )

        def _task() -> TrackedTaskResult[bool]:
            result: GitCommitPushResult = run_git_commit_push_sync(
                git_root=offer.git_root,
                file_path=offer.file_path,
                commit_message=offer.message,
            )
            return TrackedTaskResult(
                success=result.success,
                message=result.message,
                payload=result.index_lock_removed,
                error=None if result.success else result.message,
            )

        def _on_complete(completion: TrackedTaskCompletion[bool]) -> None:
            self.notify(
                completion.message,
                severity="information" if completion.success else "error",
            )
            if completion.payload:
                self.notify(
                    git_index_lock_retry_message(offer.git_root),
                    severity="warning",
                )

        submit = getattr(self.app, "_submit_tracked_task", None)
        if submit is None:
            self.notify(
                "Could not commit: background task queue unavailable.",
                severity="error",
            )
            return
        submit(
            "config-commit",
            offer.rel_path,
            offer.git_root,
            _task,
            display_name=f"commit alias {offer.rel_path}",
            dedup_key=f"config-commit:{offer.git_root}:{offer.rel_path}",
            duplicate_message=(
                f"Another config commit is already running for {offer.rel_path}."
            ),
            on_complete=_on_complete,
            reload_on_complete=False,
            notify_on_complete=False,
        )
