"""Temporary-override workflow for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.llm_provider import AliasView, TemporaryLLMOverride
from sase.llm_provider.registry import format_provider_model_label

from .custom_model_input_modal import CustomModelInputModal
from .duration_choice_modal import DurationChoiceCancelled
from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from .models_panel_duration import (
    DurationPickerModal,
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen,
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


class ModelsPanelOverrideMixin(_MixinBase):
    """Set and clear time-bound model alias overrides."""

    if TYPE_CHECKING:
        _changed: bool
        _clear_worker: Worker[tuple[bool | None, str | None]] | None
        _clear_write_alias: str
        _override_worker: Worker[tuple[TemporaryLLMOverride | None, str | None]] | None
        _override_write_alias: str
        _override_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        )
        _pending_alias: str
        _pending_raw_model: str

        def _selected_alias(self) -> AliasView | None: ...

        def _refresh_rows(self, *, keep: str | None = None) -> None: ...

        def _clear_alias_override(self, alias: str) -> bool: ...

        def _set_alias_override(
            self, alias: str, raw_model: str, seconds: float | None
        ) -> TemporaryLLMOverride: ...

        def _set_alias_override_until(
            self, alias: str, raw_model: str, expires_at: float
        ) -> TemporaryLLMOverride: ...

    def action_override(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            return
        view = self._selected_alias()
        if view is None:
            return
        self._pending_alias = view.name
        self.app.push_screen(
            ModelPickerModal(
                title=f"Override Model — @{view.name}",
                include_default_option=False,
            ),
            callback=self._on_model_picked,
        )

    def action_clear(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            return
        view = self._selected_alias()
        if view is None:
            return
        if view.override is None:
            self.notify(f"No active override on @{view.name}", severity="warning")
            return
        alias = view.name

        def task() -> tuple[bool | None, str | None]:
            try:
                return self._clear_alias_override(alias), None
            except Exception as exc:
                return None, str(exc)

        self._clear_write_alias = alias
        self._clear_worker = self.run_worker(task, thread=True, exclusive=True)

    def _on_model_picked(self, result: str | None) -> None:
        if result is None:
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Override Model",
                    hint="Format: provider/model  or  model",
                    placeholder="e.g. opencode/anthropic/claude-sonnet-4-5",
                ),
                callback=self._on_custom_picked,
            )
            return
        self._pending_raw_model = result
        self._open_duration_picker()

    def _on_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        self._pending_raw_model = result
        self._open_duration_picker()

    def _open_duration_picker(self) -> None:
        self.app.push_screen(DurationPickerModal(), callback=self._on_duration_picked)

    def _on_duration_picked(
        self, result: OverrideDurationResult | DurationChoiceCancelled | None
    ) -> None:
        if result is None or isinstance(result, DurationChoiceCancelled):
            return
        if isinstance(result, OpenOverrideUntil):
            self.app.push_screen(
                OverrideUntilModal(),
                callback=self._on_override_until_picked,
            )
            return
        self._submit_override_write(result)

    def _on_override_until_picked(
        self,
        result: ResolvedOverrideUntil | OverrideUntilBack | None,
    ) -> None:
        if result is None:
            return
        if isinstance(result, OverrideUntilBack):
            self._open_duration_picker()
            return
        self._submit_override_write(result)

    def _submit_override_write(
        self,
        result: (
            RelativeOverrideDuration | OverrideUntilCleared | ResolvedOverrideUntil
        ),
    ) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            return
        alias = self._pending_alias
        raw_model = self._pending_raw_model

        def task() -> tuple[TemporaryLLMOverride | None, str | None]:
            try:
                if isinstance(result, ResolvedOverrideUntil):
                    return (
                        self._set_alias_override_until(
                            alias,
                            raw_model,
                            result.expires_at,
                        ),
                        None,
                    )
                seconds = (
                    result.seconds
                    if isinstance(result, RelativeOverrideDuration)
                    else None
                )
                return self._set_alias_override(alias, raw_model, seconds), None
            except Exception as exc:
                return None, str(exc)

        self._override_write_alias = alias
        self._override_write_result = result
        self._override_worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._override_worker:
            self._on_override_worker(event)
        elif event.worker is self._clear_worker:
            self._on_clear_worker(event)

    def _on_override_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        alias = self._override_write_alias
        result = self._override_write_result
        self._override_worker = None
        self._override_write_alias = ""
        self._override_write_result = None
        if event.state == WorkerState.ERROR:
            detail = str(event.worker.error or "unknown error")
            self.notify(f"Could not set override: {detail}", severity="error")
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify("Could not set override: unknown error", severity="error")
            return
        override, error = worker_result
        if error is not None or override is None:
            self.notify(
                f"Could not set override: {error or 'unknown error'}",
                severity="error",
            )
            return
        label = format_provider_model_label(override.provider, override.model)
        if isinstance(result, ResolvedOverrideUntil):
            suffix = f"until {result.notification_display}"
        elif isinstance(result, OverrideUntilCleared):
            suffix = "until cleared"
        elif isinstance(result, RelativeOverrideDuration):
            suffix = f"for {format_duration_chosen(result.seconds)}"
        else:
            self.notify("Could not set override: invalid result", severity="error")
            return
        self.notify(f"@{alias} override: {label} {suffix}")
        self._changed = True
        self._refresh_rows(keep=alias)

    def _on_clear_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        alias = self._clear_write_alias
        self._clear_worker = None
        self._clear_write_alias = ""
        if event.state == WorkerState.ERROR:
            detail = str(event.worker.error or "unknown error")
            self.notify(f"Could not clear override: {detail}", severity="error")
            return
        worker_result = event.worker.result
        if worker_result is None:
            self.notify("Could not clear override: unknown error", severity="error")
            return
        cleared, error = worker_result
        if error is not None:
            self.notify(f"Could not clear override: {error}", severity="error")
            return
        if not cleared:
            self.notify(f"No active override on @{alias}", severity="warning")
            self._refresh_rows(keep=alias)
            return
        self.notify(f"Cleared override on @{alias}")
        self._changed = True
        self._refresh_rows(keep=alias)
