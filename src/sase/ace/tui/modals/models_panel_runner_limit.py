"""Persistent and temporary Models-panel runner-limit workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.config import (
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)

from .config_commit import (
    ConfigCommitOffer,
    push_config_commit_prompt,
    submit_config_commit_task,
)
from .duration_choice_modal import DurationChoiceCancelled
from .models_panel_duration import (
    DurationPickerModal,
    KeepCurrentWindow,
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen,
)
from .models_panel_runner_limit_cards import (
    RunnerLimitAction,
    RunnerLimitActionModal,
    RunnerLimitMode,
    RunnerLimitValueModal,
)
from .models_panel_runner_limit_edit import (
    RunnerLimitEditOutcome,
    RunnerLimitEditPreviewModal,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelRunnerLimitMixin(_MixinBase):
    """Manage the live machine-wide maximum-running-agents limit."""

    if TYPE_CHECKING:
        _changed: bool
        _runner_limit_clear_worker: Worker[tuple[bool | None, str | None]] | None
        _runner_limit_commit_offer_worker: Worker[ConfigCommitOffer | None] | None
        _runner_limit_override_worker: (
            Worker[tuple[TemporaryRunnerLimitOverride | None, str | None]] | None
        )
        _runner_limit_snapshot: EffectiveRunnerLimitSnapshot
        _runner_limit_snapshot_worker: (
            Worker[tuple[EffectiveRunnerLimitSnapshot, bool]] | None
        )
        _runner_limit_uses_chezmoi: bool
        _runner_limit_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        )
        _runner_limit_write_value: int | None

        def _models_panel_now(self) -> float: ...

        def _update_context(self) -> None: ...

        def _highlighted_row_id(self) -> str | None: ...

        def _replace_display(self, *, keep: str | None = None) -> None: ...

        def _load_effective_runner_limit_snapshot(
            self,
        ) -> tuple[EffectiveRunnerLimitSnapshot, bool]: ...

        def _set_runner_limit_override(
            self, limit: int, seconds: float | None
        ) -> TemporaryRunnerLimitOverride: ...

        def _set_runner_limit_override_until(
            self, limit: int, expires_at: float
        ) -> TemporaryRunnerLimitOverride: ...

        def _clear_runner_limit_override(self) -> bool: ...

        def _build_runner_limit_commit_offer(
            self, path: str
        ) -> ConfigCommitOffer | None: ...

        def _request_agents_refresh(self, source: str) -> None: ...

        def _mark_changed(
            self,
            *,
            provider_routing_changed: bool = False,
            agents_refresh: str | None = None,
        ) -> None: ...

    def _start_runner_limit_snapshot_load(self) -> None:
        worker = self._runner_limit_snapshot_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> tuple[EffectiveRunnerLimitSnapshot, bool]:
            return self._load_effective_runner_limit_snapshot()

        self._runner_limit_snapshot_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-runner-limit-snapshot",
        )

    def _refresh_runner_limit_clock(self) -> None:
        self._apply_runner_limit_snapshot(self._runner_limit_snapshot)

    def _apply_runner_limit_snapshot(
        self, snapshot: EffectiveRunnerLimitSnapshot
    ) -> None:
        self._runner_limit_snapshot = snapshot
        if self.is_mounted:  # type: ignore[attr-defined]
            self._replace_display(keep=self._highlighted_row_id())

    def action_manage_runner_limit(self) -> None:
        if self._runner_limit_write_busy():
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            RunnerLimitActionModal(
                self._runner_limit_snapshot,
                now=self._models_panel_now(),
                use_chezmoi=self._runner_limit_uses_chezmoi,
            ),
            callback=self._on_runner_limit_action,
        )

    def _on_runner_limit_action(self, result: RunnerLimitAction | None) -> None:
        if result is None:
            return
        if result == "clear":
            self._submit_runner_limit_clear()
            return
        now = self._models_panel_now()
        initial = (
            self._runner_limit_snapshot.configured_limit
            if result == "edit"
            else self._runner_limit_snapshot.effective_limit(now)
        )
        self.app.push_screen(  # type: ignore[attr-defined]
            RunnerLimitValueModal(result, initial=initial),
            callback=lambda value: self._on_runner_limit_value(result, value),
        )

    def _on_runner_limit_value(self, mode: RunnerLimitMode, value: int | None) -> None:
        if value is None:
            return
        if mode == "edit":
            self.app.push_screen(  # type: ignore[attr-defined]
                RunnerLimitEditPreviewModal(
                    value,
                    override_active=(
                        self._runner_limit_snapshot.active_override(
                            self._models_panel_now()
                        )
                        is not None
                    ),
                ),
                callback=self._on_runner_limit_edited,
            )
            return
        self._runner_limit_write_value = value
        self._open_runner_limit_duration_picker()

    def _open_runner_limit_duration_picker(self) -> None:
        self.app.push_screen(  # type: ignore[attr-defined]
            DurationPickerModal(), callback=self._on_runner_limit_duration_picked
        )

    def _on_runner_limit_duration_picked(
        self,
        result: OverrideDurationResult | DurationChoiceCancelled | None,
    ) -> None:
        if result is None or isinstance(result, DurationChoiceCancelled):
            return
        if isinstance(result, KeepCurrentWindow):
            return
        if isinstance(result, OpenOverrideUntil):
            self.app.push_screen(  # type: ignore[attr-defined]
                OverrideUntilModal(), callback=self._on_runner_limit_until_picked
            )
            return
        self._submit_runner_limit_override(result)

    def _on_runner_limit_until_picked(
        self,
        result: ResolvedOverrideUntil | OverrideUntilBack | None,
    ) -> None:
        if result is None:
            return
        if isinstance(result, OverrideUntilBack):
            self._open_runner_limit_duration_picker()
            return
        self._submit_runner_limit_override(result)

    def _submit_runner_limit_override(
        self,
        result: (
            RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil
        ),
    ) -> None:
        if self._runner_limit_write_busy() or self._runner_limit_write_value is None:
            return
        limit = self._runner_limit_write_value

        def task() -> tuple[TemporaryRunnerLimitOverride | None, str | None]:
            try:
                if isinstance(result, ResolvedOverrideUntil):
                    return (
                        self._set_runner_limit_override_until(limit, result.expires_at),
                        None,
                    )
                seconds = (
                    result.seconds
                    if isinstance(result, RelativeOverrideDuration)
                    else None
                )
                return self._set_runner_limit_override(limit, seconds), None
            except Exception as error:  # noqa: BLE001 - worker reports errors.
                return None, str(error)

        self._runner_limit_write_result = result
        self._runner_limit_override_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-runner-limit-write",
        )

    def _submit_runner_limit_clear(self) -> None:
        if self._runner_limit_write_busy():
            return

        def task() -> tuple[bool | None, str | None]:
            try:
                return self._clear_runner_limit_override(), None
            except Exception as error:  # noqa: BLE001 - worker reports errors.
                return None, str(error)

        self._runner_limit_clear_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-runner-limit-clear",
        )

    def _on_runner_limit_edited(self, outcome: object | None) -> None:
        if not isinstance(outcome, RunnerLimitEditOutcome):
            return
        now = self._models_panel_now()
        previous_override = self._runner_limit_snapshot.active_override(now)
        self._apply_runner_limit_snapshot(
            EffectiveRunnerLimitSnapshot(
                configured_limit=outcome.configured_limit,
                temporary_override=previous_override,
                captured_at=now,
            )
        )
        message = f"Configured max running agents: {outcome.configured_limit}"
        if outcome.configured_limit != outcome.requested_limit:
            message += f" (requested {outcome.requested_limit}; overlay still wins)"
        if previous_override is not None:
            message += "; temporary override remains active"
        self.notify(message)  # type: ignore[attr-defined]
        self._mark_changed(agents_refresh="models-runner-limit-config")
        self._offer_runner_limit_commit(outcome.applied.path)

    def _offer_runner_limit_commit(self, path: str) -> None:
        worker = self._runner_limit_commit_offer_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> ConfigCommitOffer | None:
            return self._build_runner_limit_commit_offer(path)

        self._runner_limit_commit_offer_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-runner-limit-commit-offer",
        )

    def _runner_limit_write_busy(self) -> bool:
        return (
            self._runner_limit_override_worker is not None
            or self._runner_limit_clear_worker is not None
        )

    def _on_runner_limit_worker_state_changed(self, event: Worker.StateChanged) -> bool:
        if event.worker is self._runner_limit_snapshot_worker:
            self._on_runner_limit_snapshot_worker(event)
            return True
        if event.worker is self._runner_limit_override_worker:
            self._on_runner_limit_override_worker(event)
            return True
        if event.worker is self._runner_limit_clear_worker:
            self._on_runner_limit_clear_worker(event)
            return True
        if event.worker is self._runner_limit_commit_offer_worker:
            self._on_runner_limit_commit_worker(event)
            return True
        return False

    def _on_runner_limit_snapshot_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._runner_limit_snapshot_worker = None
        if event.state == WorkerState.SUCCESS and self.is_mounted:  # type: ignore[attr-defined]
            worker_result = event.worker.result
            if worker_result is None:
                return
            snapshot, use_chezmoi = worker_result
            self._runner_limit_uses_chezmoi = use_chezmoi
            self._apply_runner_limit_snapshot(snapshot)
        elif event.state == WorkerState.ERROR and self.is_mounted:  # type: ignore[attr-defined]
            self.notify(  # type: ignore[attr-defined]
                f"Could not load max running agents: {event.worker.error}",
                severity="warning",
            )

    def _on_runner_limit_override_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        chosen_duration = self._runner_limit_write_result
        self._runner_limit_override_worker = None
        self._runner_limit_write_result = None
        self._runner_limit_write_value = None
        if event.state == WorkerState.ERROR:
            self.notify(  # type: ignore[attr-defined]
                f"Could not set runner-limit override: {event.worker.error}",
                severity="error",
            )
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify(  # type: ignore[attr-defined]
                "Could not set runner-limit override: unknown error",
                severity="error",
            )
            return
        override, error = worker_result
        if error is not None or override is None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not set runner-limit override: {error or 'unknown error'}",
                severity="error",
            )
            return
        self._apply_runner_limit_snapshot(
            EffectiveRunnerLimitSnapshot(
                configured_limit=self._runner_limit_snapshot.configured_limit,
                temporary_override=override,
                captured_at=self._models_panel_now(),
            )
        )
        if isinstance(chosen_duration, ResolvedOverrideUntil):
            suffix = f"until {chosen_duration.notification_display}"
        elif isinstance(chosen_duration, OverrideUntilCleared):
            suffix = "until cleared"
        elif isinstance(chosen_duration, RelativeOverrideDuration):
            suffix = f"for {format_duration_chosen(chosen_duration.seconds)}"
        else:
            suffix = "temporarily"
        self.notify(  # type: ignore[attr-defined]
            f"Max running agents override: {override.limit} {suffix}"
        )
        self._mark_changed(agents_refresh="models-runner-limit-override")

    def _on_runner_limit_clear_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        self._runner_limit_clear_worker = None
        if event.state == WorkerState.ERROR:
            self.notify(  # type: ignore[attr-defined]
                f"Could not clear runner-limit override: {event.worker.error}",
                severity="error",
            )
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify(  # type: ignore[attr-defined]
                "Could not clear runner-limit override: unknown error",
                severity="error",
            )
            return
        cleared, error = worker_result
        if error is not None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not clear runner-limit override: {error}", severity="error"
            )
            return
        self._apply_runner_limit_snapshot(
            EffectiveRunnerLimitSnapshot(
                configured_limit=self._runner_limit_snapshot.configured_limit,
                temporary_override=None,
                captured_at=self._models_panel_now(),
            )
        )
        if cleared:
            self.notify("Cleared max-running-agents override")  # type: ignore[attr-defined]
            self._mark_changed(agents_refresh="models-runner-limit-clear")
        else:
            self.notify(  # type: ignore[attr-defined]
                "No active max-running-agents override", severity="warning"
            )

    def _on_runner_limit_commit_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._runner_limit_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:  # type: ignore[attr-defined]
            return
        offer = event.worker.result
        if offer is not None:
            push_config_commit_prompt(
                self.app,  # type: ignore[attr-defined]
                offer,
                message="Commit and push your max-running-agents change?",
                on_confirm=self._submit_runner_limit_commit,
            )

    def _submit_runner_limit_commit(self, offer: ConfigCommitOffer) -> None:
        submit_config_commit_task(
            self.app,  # type: ignore[attr-defined]
            offer,
            display_name=f"commit max running agents {offer.rel_path}",
        )

    def _cancel_runner_limit_workers(self) -> None:
        for name in (
            "_runner_limit_snapshot_worker",
            "_runner_limit_override_worker",
            "_runner_limit_clear_worker",
            "_runner_limit_commit_offer_worker",
        ):
            worker: Worker[Any] | None = getattr(self, name)
            setattr(self, name, None)
            if worker is not None and not worker.is_finished:
                worker.cancel()


__all__ = ["ModelsPanelRunnerLimitMixin"]
