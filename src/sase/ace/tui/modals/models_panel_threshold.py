"""Persistent big-epic threshold workflow for Launch Control."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from .config_commit import (
    ConfigCommitOffer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from .models_panel_rows import BigEpicPhaseThresholdSettingRow
from .models_panel_threshold_cards import BigEpicPhaseThresholdValueModal
from .models_panel_threshold_edit import (
    BigEpicPhaseThresholdEditOutcome,
    BigEpicPhaseThresholdEditPreviewModal,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelThresholdMixin(_MixinBase):
    """Manage the persistent big-epic authored-phase threshold."""

    if TYPE_CHECKING:
        _changed: bool
        _threshold_commit_offer_worker: Worker[ConfigCommitOffer | None] | None

        def _selected_row(self) -> object | None: ...

        def _start_provider_snapshot_load(
            self,
            *,
            keep: str | None = None,
            update_rows: bool = False,
            signal_changes: bool = False,
        ) -> None: ...

        def _build_big_epic_phase_threshold_commit_offer(
            self, path: str
        ) -> ConfigCommitOffer | None: ...

        def _mark_changed(
            self,
            *,
            provider_routing_changed: bool = False,
            agents_refresh: str | None = None,
        ) -> None: ...

    def action_edit_big_epic_phase_threshold(self) -> None:
        row = self._selected_row()
        if not isinstance(row, BigEpicPhaseThresholdSettingRow):
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            BigEpicPhaseThresholdValueModal(initial=row.threshold),
            callback=self._on_big_epic_phase_threshold_value,
        )

    def action_reset_big_epic_phase_threshold(self) -> None:
        if self._threshold_write_busy():
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            BigEpicPhaseThresholdEditPreviewModal(None, reset=True),
            callback=self._on_big_epic_phase_threshold_edited,
        )

    def _on_big_epic_phase_threshold_value(self, value: int | None) -> None:
        if value is None or self._threshold_write_busy():
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            BigEpicPhaseThresholdEditPreviewModal(value),
            callback=self._on_big_epic_phase_threshold_edited,
        )

    def _on_big_epic_phase_threshold_edited(self, outcome: object | None) -> None:
        if not isinstance(outcome, BigEpicPhaseThresholdEditOutcome):
            return
        self._mark_changed()
        self._start_provider_snapshot_load(
            keep="setting:big_epic_phase_threshold",
            update_rows=True,
            signal_changes=True,
        )
        if outcome.requested_threshold is None:
            message = (
                "Reset big-epic threshold; effective value is "
                f"{outcome.effective_threshold}"
            )
        else:
            message = f"Configured big-epic threshold: {outcome.effective_threshold}"
            if outcome.effective_threshold != outcome.requested_threshold:
                message += (
                    f" (requested {outcome.requested_threshold}; "
                    "higher-precedence config still wins)"
                )
        self.notify(message)  # type: ignore[attr-defined]
        self._offer_big_epic_phase_threshold_commit(outcome.applied.path)

    def _offer_big_epic_phase_threshold_commit(self, path: str) -> None:
        worker = self._threshold_commit_offer_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> ConfigCommitOffer | None:
            return self._build_big_epic_phase_threshold_commit_offer(path)

        self._threshold_commit_offer_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-threshold-commit-offer",
        )

    def _threshold_write_busy(self) -> bool:
        worker = self._threshold_commit_offer_worker
        return worker is not None and not worker.is_finished

    def _on_threshold_worker_state_changed(self, event: Worker.StateChanged) -> bool:
        if event.worker is not self._threshold_commit_offer_worker:
            return False
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return True
        self._threshold_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:  # type: ignore[attr-defined]
            return True
        offer = event.worker.result
        if offer is not None:
            push_config_commit_prompt(
                self.app,  # type: ignore[attr-defined]
                offer,
                message="Commit and push your big-epic threshold change?",
                on_confirm=self._submit_big_epic_phase_threshold_commit,
            )
        return True

    def _submit_big_epic_phase_threshold_commit(self, offer: ConfigCommitOffer) -> None:
        submit_config_commit_task(
            self.app,  # type: ignore[attr-defined]
            offer,
            display_name=f"commit big epic threshold {offer.rel_path}",
        )

    def _cancel_threshold_workers(self) -> None:
        worker: Worker[Any] | None = self._threshold_commit_offer_worker
        self._threshold_commit_offer_worker = None
        if worker is not None and not worker.is_finished:
            worker.cancel()


__all__ = ["ModelsPanelThresholdMixin"]
