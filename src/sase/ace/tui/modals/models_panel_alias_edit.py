"""Persistent alias-edit and commit workflow for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerState

from sase.config import ConfigEditOp
from sase.llm_provider import AliasView
from sase.llm_provider.config import validate_model_alias_pool_value

from .config_commit import push_config_commit_prompt, submit_config_commit_task
from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
    alias_reference_rejection,
)
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
        _pending_alias_selection: AliasSelectionContext | None
        _config_commit_offer_worker: Worker[AliasCommitOffer | None] | None
        _views: list[AliasView]

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
        self._pending_alias_selection = AliasSelectionContext(
            views=tuple(self._views),
            target_alias=view.name,
            operation="persistent",
        )
        self.app.push_screen(
            ModelPickerModal(
                title=f"Edit Model — @{view.name}",
                include_default_option=False,
                alias_context=self._pending_alias_selection,
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
        rejection = alias_reference_rejection(self._pending_alias_selection, result)
        if rejection is not None:
            self.notify(
                f"Cannot set @{view.name} to {result.strip()}: {rejection}.",
                severity="warning",
            )
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Alias Value",
                    hint=(
                        "Format: provider/model, model, @alias, or a | separated pool"
                    ),
                    placeholder=("e.g. claude/opus@medium | codex/gpt-5.5"),
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
        rejection = alias_reference_rejection(self._pending_alias_selection, result)
        if rejection is not None:
            self.notify(
                f"Cannot set @{view.name} to {result.strip()}: {rejection}.",
                severity="warning",
            )
            return
        self._open_model_edit_preview(view, result)

    def _open_model_edit_preview(self, view: AliasView, model: str) -> None:
        pool_errors = validate_model_alias_pool_value(view.name, model)
        if pool_errors:
            self.notify(
                f"Cannot set @{view.name}: {pool_errors[0]}",
                severity="warning",
            )
            return
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
        worker = self._config_commit_offer_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        path = outcome.applied.path
        op = outcome.applied.op
        alias = outcome.alias

        def task() -> AliasCommitOffer | None:
            return self._build_alias_commit_offer(path, op=op, alias=alias)

        self._config_commit_offer_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-config-commit-offer",
        )

    def _on_config_commit_offer_worker_state(self, event: Worker.StateChanged) -> bool:
        """Handle alias commit discovery, returning whether it owned *event*."""
        if event.worker is not self._config_commit_offer_worker:
            return False
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return True
        self._config_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:  # type: ignore[attr-defined]
            return True
        offer = event.worker.result
        if offer is not None:
            push_config_commit_prompt(
                self.app,  # type: ignore[attr-defined]
                offer,
                message="Commit and push your model-alias change?",
                on_confirm=self._submit_commit_task,
            )
        return True

    def _cancel_config_commit_offer(self) -> None:
        worker = self._config_commit_offer_worker
        self._config_commit_offer_worker = None
        if worker is not None and not worker.is_finished:
            worker.cancel()

    def _submit_commit_task(self, offer: AliasCommitOffer) -> None:
        submit_config_commit_task(
            self.app,  # type: ignore[attr-defined]
            offer,
            display_name=f"commit alias {offer.rel_path}",
        )
