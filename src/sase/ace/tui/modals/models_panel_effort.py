"""Default-effort action, persistent edit, and temporary override workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.llm_provider import (
    EffectiveDefaultEffortSnapshot,
    TemporaryEffortOverride,
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
from .models_panel_effort_cards import (
    DefaultEffortAction,
    DefaultEffortActionModal,
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
    DefaultEffortPickerMode,
)
from .models_panel_effort_edit import (
    DefaultEffortEditOutcome,
    DefaultEffortEditPreviewModal,
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


class ModelsPanelEffortMixin(_MixinBase):
    """Manage the global default reasoning-effort control."""

    if TYPE_CHECKING:
        _changed: bool
        _default_effort: str | None
        _effort_clear_worker: Worker[tuple[bool | None, str | None]] | None
        _effort_commit_offer_worker: Worker[ConfigCommitOffer | None] | None
        _effort_override_worker: (
            Worker[tuple[TemporaryEffortOverride | None, str | None]] | None
        )
        _effort_snapshot: EffectiveDefaultEffortSnapshot
        _effort_snapshot_worker: (
            Worker[tuple[EffectiveDefaultEffortSnapshot, bool]] | None
        )
        _effort_uses_chezmoi: bool
        _effort_write_level: str | None
        _effort_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        )

        def _models_panel_now(self) -> float: ...

        def _update_context(self) -> None: ...

        def _highlighted_row_id(self) -> str | None: ...

        def _replace_display(self, *, keep: str | None = None) -> None: ...

        def _load_effective_effort_snapshot(
            self,
        ) -> tuple[EffectiveDefaultEffortSnapshot, bool]: ...

        def _set_default_effort_override(
            self, effort: str, seconds: float | None
        ) -> TemporaryEffortOverride: ...

        def _set_default_effort_override_until(
            self, effort: str, expires_at: float
        ) -> TemporaryEffortOverride: ...

        def _clear_default_effort_override(self) -> bool: ...

        def _build_default_effort_commit_offer(
            self, path: str
        ) -> ConfigCommitOffer | None: ...

        def _mark_changed(
            self,
            *,
            provider_routing_changed: bool = False,
            agents_refresh: str | None = None,
        ) -> None: ...

    def _start_effort_snapshot_load(self) -> None:
        """Load configured/state data once, outside Textual's event loop."""
        worker = self._effort_snapshot_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> tuple[EffectiveDefaultEffortSnapshot, bool]:
            return self._load_effective_effort_snapshot()

        self._effort_snapshot_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-effort-snapshot",
        )

    def _refresh_effort_clock(self) -> None:
        """Refresh countdown/expiry from the captured snapshot without I/O."""
        self._apply_effort_snapshot(self._effort_snapshot)

    def _apply_effort_snapshot(self, snapshot: EffectiveDefaultEffortSnapshot) -> None:
        self._effort_snapshot = snapshot
        self._default_effort = snapshot.effective_effort(self._models_panel_now())
        if self.is_mounted:  # type: ignore[attr-defined]
            self._replace_display(keep=self._highlighted_row_id())

    def action_manage_default_effort(self) -> None:
        if self._effort_write_busy():
            return
        now = self._models_panel_now()
        self.app.push_screen(  # type: ignore[attr-defined]
            DefaultEffortActionModal(
                self._effort_snapshot,
                now=now,
                use_chezmoi=self._effort_uses_chezmoi,
            ),
            callback=self._on_default_effort_action,
        )

    def _on_default_effort_action(self, result: DefaultEffortAction | None) -> None:
        if result is None:
            return
        if result == "clear":
            self._submit_effort_clear()
            return
        self.app.push_screen(  # type: ignore[attr-defined]
            DefaultEffortLevelModal(
                result,
                self._effort_snapshot,
                now=self._models_panel_now(),
            ),
            callback=lambda choice: self._on_default_effort_level(result, choice),
        )

    def _on_default_effort_level(
        self,
        mode: DefaultEffortPickerMode,
        result: DefaultEffortLevelChoice | None,
    ) -> None:
        if result is None:
            return
        if mode == "edit":
            self.app.push_screen(  # type: ignore[attr-defined]
                DefaultEffortEditPreviewModal(
                    result.effort,
                    override_active=(
                        self._effort_snapshot.active_override(self._models_panel_now())
                        is not None
                    ),
                ),
                callback=self._on_default_effort_edited,
            )
            return
        if result.effort is None:
            return
        self._effort_write_level = result.effort
        self._open_effort_duration_picker()

    def _open_effort_duration_picker(self) -> None:
        self.app.push_screen(  # type: ignore[attr-defined]
            DurationPickerModal(), callback=self._on_effort_duration_picked
        )

    def _on_effort_duration_picked(
        self,
        result: OverrideDurationResult | DurationChoiceCancelled | None,
    ) -> None:
        if result is None or isinstance(result, DurationChoiceCancelled):
            return
        if isinstance(result, KeepCurrentWindow):
            return
        if isinstance(result, OpenOverrideUntil):
            self.app.push_screen(  # type: ignore[attr-defined]
                OverrideUntilModal(), callback=self._on_effort_until_picked
            )
            return
        self._submit_effort_override(result)

    def _on_effort_until_picked(
        self,
        result: ResolvedOverrideUntil | OverrideUntilBack | None,
    ) -> None:
        if result is None:
            return
        if isinstance(result, OverrideUntilBack):
            self._open_effort_duration_picker()
            return
        self._submit_effort_override(result)

    def _submit_effort_override(
        self,
        result: (
            RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil
        ),
    ) -> None:
        if self._effort_write_busy() or self._effort_write_level is None:
            return
        effort = self._effort_write_level

        def task() -> tuple[TemporaryEffortOverride | None, str | None]:
            try:
                if isinstance(result, ResolvedOverrideUntil):
                    return (
                        self._set_default_effort_override_until(
                            effort, result.expires_at
                        ),
                        None,
                    )
                seconds = (
                    result.seconds
                    if isinstance(result, RelativeOverrideDuration)
                    else None
                )
                return self._set_default_effort_override(effort, seconds), None
            except Exception as exc:
                return None, str(exc)

        self._effort_write_result = result
        self._effort_override_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-effort-write",
        )

    def _submit_effort_clear(self) -> None:
        if self._effort_write_busy():
            return

        def task() -> tuple[bool | None, str | None]:
            try:
                return self._clear_default_effort_override(), None
            except Exception as exc:
                return None, str(exc)

        self._effort_clear_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-effort-clear",
        )

    def _on_default_effort_edited(self, outcome: object | None) -> None:
        if not isinstance(outcome, DefaultEffortEditOutcome):
            return
        now = self._models_panel_now()
        previous_override = self._effort_snapshot.active_override(now)
        self._apply_effort_snapshot(
            EffectiveDefaultEffortSnapshot(
                configured_effort=outcome.effort,
                temporary_override=previous_override,
                captured_at=now,
            )
        )
        label = f"@{outcome.effort}" if outcome.effort else "provider default"
        message = f"Configured default effort: {label}"
        if previous_override is not None:
            message += "; temporary override remains active"
        self.notify(message)  # type: ignore[attr-defined]
        self._mark_changed()
        self._offer_default_effort_commit(outcome.applied.path)

    def _offer_default_effort_commit(self, path: str) -> None:
        worker = self._effort_commit_offer_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()

        def task() -> ConfigCommitOffer | None:
            return self._build_default_effort_commit_offer(path)

        self._effort_commit_offer_worker = self.run_worker(  # type: ignore[attr-defined]
            task,
            thread=True,
            exclusive=True,
            group="models-effort-commit-offer",
        )

    def _effort_write_busy(self) -> bool:
        return (
            self._effort_override_worker is not None
            or self._effort_clear_worker is not None
        )

    def _on_effort_worker_state_changed(self, event: Worker.StateChanged) -> bool:
        if event.worker is self._effort_snapshot_worker:
            self._on_effort_snapshot_worker(event)
            return True
        if event.worker is self._effort_override_worker:
            self._on_effort_override_worker(event)
            return True
        if event.worker is self._effort_clear_worker:
            self._on_effort_clear_worker(event)
            return True
        if event.worker is self._effort_commit_offer_worker:
            self._on_effort_commit_worker(event)
            return True
        return False

    def _on_effort_snapshot_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._effort_snapshot_worker = None
        if event.state == WorkerState.SUCCESS and self.is_mounted:  # type: ignore[attr-defined]
            worker_result = event.worker.result
            if worker_result is None:
                return
            snapshot, use_chezmoi = worker_result
            self._effort_uses_chezmoi = use_chezmoi
            self._apply_effort_snapshot(snapshot)
        elif event.state == WorkerState.ERROR and self.is_mounted:  # type: ignore[attr-defined]
            self.notify(  # type: ignore[attr-defined]
                f"Could not load default effort: {event.worker.error}",
                severity="warning",
            )

    def _on_effort_override_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        result = self._effort_write_result
        self._effort_override_worker = None
        self._effort_write_result = None
        self._effort_write_level = None
        if event.state == WorkerState.ERROR:
            self.notify(  # type: ignore[attr-defined]
                f"Could not set effort override: {event.worker.error}",
                severity="error",
            )
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify(  # type: ignore[attr-defined]
                "Could not set effort override: unknown error", severity="error"
            )
            return
        override, error = worker_result
        if error is not None or override is None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not set effort override: {error or 'unknown error'}",
                severity="error",
            )
            return
        self._apply_effort_snapshot(
            EffectiveDefaultEffortSnapshot(
                configured_effort=self._effort_snapshot.configured_effort,
                temporary_override=override,
                captured_at=self._models_panel_now(),
            )
        )
        if isinstance(result, ResolvedOverrideUntil):
            suffix = f"until {result.notification_display}"
        elif isinstance(result, OverrideUntilCleared):
            suffix = "until cleared"
        elif isinstance(result, RelativeOverrideDuration):
            suffix = f"for {format_duration_chosen(result.seconds)}"
        else:
            suffix = "temporarily"
        self.notify(  # type: ignore[attr-defined]
            f"Default effort override: @{override.effort} {suffix}"
        )
        self._mark_changed()

    def _on_effort_clear_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        self._effort_clear_worker = None
        if event.state == WorkerState.ERROR:
            self.notify(  # type: ignore[attr-defined]
                f"Could not clear effort override: {event.worker.error}",
                severity="error",
            )
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify(  # type: ignore[attr-defined]
                "Could not clear effort override: unknown error", severity="error"
            )
            return
        cleared, error = worker_result
        if error is not None:
            self.notify(  # type: ignore[attr-defined]
                f"Could not clear effort override: {error}", severity="error"
            )
            return
        self._apply_effort_snapshot(
            EffectiveDefaultEffortSnapshot(
                configured_effort=self._effort_snapshot.configured_effort,
                temporary_override=None,
                captured_at=self._models_panel_now(),
            )
        )
        if cleared:
            self.notify("Cleared default effort override")  # type: ignore[attr-defined]
            self._mark_changed()
        else:
            self.notify(  # type: ignore[attr-defined]
                "No active default effort override", severity="warning"
            )

    def _on_effort_commit_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (
            WorkerState.SUCCESS,
            WorkerState.ERROR,
            WorkerState.CANCELLED,
        ):
            return
        self._effort_commit_offer_worker = None
        if event.state != WorkerState.SUCCESS or not self.is_mounted:  # type: ignore[attr-defined]
            return
        offer = event.worker.result
        if offer is not None:
            push_config_commit_prompt(
                self.app,  # type: ignore[attr-defined]
                offer,
                message="Commit and push your default-effort change?",
                on_confirm=self._submit_default_effort_commit,
            )

    def _submit_default_effort_commit(self, offer: ConfigCommitOffer) -> None:
        submit_config_commit_task(
            self.app,  # type: ignore[attr-defined]
            offer,
            display_name=f"commit default effort {offer.rel_path}",
        )

    def _cancel_effort_workers(self) -> None:
        for name in (
            "_effort_snapshot_worker",
            "_effort_override_worker",
            "_effort_clear_worker",
            "_effort_commit_offer_worker",
        ):
            worker: Worker[Any] | None = getattr(self, name)
            setattr(self, name, None)
            if worker is not None and not worker.is_finished:
                worker.cancel()


__all__ = ["ModelsPanelEffortMixin"]
