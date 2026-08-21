"""Temporary-override workflow for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.worker import Worker, WorkerState

from sase.llm_provider import (
    AliasView,
    EffectiveDefaultEffortSnapshot,
    TemporaryLLMOverride,
    TemporaryProviderDisable,
)
from sase.llm_provider.registry import format_provider_model_label
from sase.xprompt.effort import split_model_effort

from .custom_model_input_modal import CustomModelInputModal
from .duration_choice_modal import DurationChoiceCancelled
from .model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
    alias_reference_rejection,
)
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
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    RunnerLimitSettingRow,
)
from .models_panel_provider_state import (
    disabled_explicit_provider_message,
    soft_explicit_provider_note,
)
from .models_panel_runner_limit_cards import RunnerLimitAction
from .models_panel_selector import parse_selector_for_display
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
        _clear_write_keep: str
        _clear_write_label: str
        _override_worker: Worker[tuple[TemporaryLLMOverride | None, str | None]] | None
        _override_write_alias: str
        _override_write_keep: str
        _override_write_label: str
        _override_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        )
        _pending_alias: str
        _pending_alias_selection: AliasSelectionContext | None
        _pending_model_target_keep: str
        _pending_model_target_label: str
        _pending_raw_model: str
        _provider_disables: dict[str, TemporaryProviderDisable]
        _views: list[AliasView]
        _effort_snapshot: EffectiveDefaultEffortSnapshot

        def _selected_row(
            self,
        ) -> (
            AliasView
            | LaunchModelSettingRow
            | DefaultEffortSettingRow
            | RunnerLimitSettingRow
            | BigEpicPhaseThresholdSettingRow
            | object
            | None
        ): ...

        def _selected_model_row(self) -> AliasView | LaunchModelSettingRow | None: ...

        def _refresh_rows(self, *, keep: str | None = None) -> None: ...

        def _models_panel_now(self) -> float: ...

        def _clear_alias_override(self, alias: str) -> bool: ...

        def _set_alias_override(
            self, alias: str, raw_model: str, seconds: float | None
        ) -> TemporaryLLMOverride: ...

        def _set_alias_override_until(
            self, alias: str, raw_model: str, expires_at: float
        ) -> TemporaryLLMOverride: ...

        def _on_default_effort_action(
            self, result: DefaultEffortAction | None
        ) -> None: ...

        def _on_runner_limit_action(self, result: RunnerLimitAction | None) -> None: ...

        def _mark_changed(
            self,
            *,
            provider_routing_changed: bool = False,
            agents_refresh: str | None = None,
        ) -> None: ...

    def action_override(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            return
        selected = self._selected_row()
        if isinstance(selected, DefaultEffortSettingRow):
            self._on_default_effort_action("override")
            return
        if isinstance(selected, RunnerLimitSettingRow):
            self._on_runner_limit_action("override")
            return
        if isinstance(selected, BigEpicPhaseThresholdSettingRow):
            self.notify(
                "big epic starts at has no temporary override; press e to edit "
                "or r to reset.",
                severity="warning",
            )
            return
        row = self._selected_model_row()
        if row is None:
            return
        key, label, keep = self._model_target_identity(row)
        self._pending_alias = key
        self._pending_model_target_label = label
        self._pending_model_target_keep = keep
        self._pending_raw_model = ""
        self._pending_alias_selection = AliasSelectionContext(
            views=tuple(self._views),
            target_alias=key,
            operation="temporary",
        )
        self.app.push_screen(
            ModelPickerModal(
                title=f"Override Model — {label}",
                include_default_option=False,
                alias_context=self._pending_alias_selection,
                provider_disables=self._provider_disables,
            ),
            callback=self._on_model_picked,
        )

    def action_clear(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            return
        selected = self._selected_row()
        if isinstance(selected, DefaultEffortSettingRow):
            self._on_default_effort_action("clear")
            return
        if isinstance(selected, RunnerLimitSettingRow):
            self._on_runner_limit_action("clear")
            return
        if isinstance(selected, BigEpicPhaseThresholdSettingRow):
            self.notify(
                "big epic starts at has no temporary override; press e to edit "
                "or r to reset.",
                severity="warning",
            )
            return
        row = self._selected_model_row()
        if row is None:
            return
        key, label, keep = self._model_target_identity(row)
        override = (
            row.snapshot.override
            if isinstance(row, LaunchModelSettingRow)
            else row.override
        )
        if override is None:
            self.notify(f"No active override on {label}", severity="warning")
            return
        alias = key

        def task() -> tuple[bool | None, str | None]:
            try:
                return self._clear_alias_override(alias), None
            except Exception as exc:
                return None, str(exc)

        self._clear_write_alias = alias
        self._clear_write_label = label
        self._clear_write_keep = keep
        self._clear_worker = self.run_worker(task, thread=True, exclusive=True)

    @staticmethod
    def _model_target_identity(
        row: AliasView | LaunchModelSettingRow,
    ) -> tuple[str, str, str]:
        """Return state key, human label, and stable row id for a model row."""
        if isinstance(row, LaunchModelSettingRow):
            return row.override_key, row.label, row.row_id
        return row.name, f"@{row.name}", row.name

    def _pending_override_label(self) -> str:
        """Return a human label for the pending temporary override target."""
        return self._pending_model_target_label or (
            f"@{self._pending_alias}" if self._pending_alias else ""
        )

    def _on_model_picked(self, result: str | None) -> None:
        if result is None:
            return
        rejection = alias_reference_rejection(self._pending_alias_selection, result)
        if rejection is not None:
            self.notify(
                f"Cannot snapshot {result.strip()} onto "
                f"{self._pending_override_label()}: "
                f"{rejection}.",
                severity="warning",
            )
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Override Model",
                    hint=(
                        "Format: model, provider/model, or @alias; "
                        "optional trailing @effort"
                    ),
                    placeholder="e.g. codex/gpt-5.6-sol@medium",
                ),
                callback=self._on_custom_picked,
            )
            return
        self._open_override_model_effort_picker(result)

    def _on_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        parsed = parse_selector_for_display(result.strip())
        if parsed.error is not None:
            self.notify(parsed.error, severity="warning")
            return
        if parsed.selector is not None:
            self.notify(
                "Pools and fallbacks are config-only; a temporary override on "
                f"{self._pending_override_label()} takes a single target. "
                "Press e to set it to a selector.",
                severity="warning",
            )
            return
        rejection = alias_reference_rejection(self._pending_alias_selection, result)
        if rejection is not None:
            self.notify(
                f"Cannot snapshot {result.strip()} onto "
                f"{self._pending_override_label()}: "
                f"{rejection}.",
                severity="warning",
            )
            return
        raw_model = result.strip()
        disabled = disabled_explicit_provider_message(
            raw_model,
            self._provider_disables,
            now=self._models_panel_now(),
        )
        if disabled is not None:
            self.notify(
                f"Cannot use {raw_model}: {disabled}.",
                severity="warning",
            )
            return
        note = soft_explicit_provider_note(
            raw_model,
            self._provider_disables,
            now=self._models_panel_now(),
        )
        if note is not None:
            self.notify(note)
        _, effort = split_model_effort(raw_model)
        if effort is None:
            self._open_override_model_effort_picker(raw_model)
            return
        self._pending_raw_model = raw_model
        self._open_duration_picker()

    def _open_override_model_effort_picker(self, raw_model: str) -> None:
        self._pending_raw_model = raw_model.strip()
        self.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                self._effort_snapshot,
                now=self._models_panel_now(),
                model=self._pending_raw_model,
            ),
            callback=self._on_override_model_effort_picked,
        )

    def _on_override_model_effort_picked(
        self,
        result: DefaultEffortLevelChoice | None,
    ) -> None:
        if result is None:
            return
        if result.effort is not None:
            self._pending_raw_model = f"{self._pending_raw_model}@{result.effort}"
        self._open_duration_picker()

    def _open_duration_picker(self) -> None:
        self.app.push_screen(DurationPickerModal(), callback=self._on_duration_picked)

    def _on_duration_picked(
        self, result: OverrideDurationResult | DurationChoiceCancelled | None
    ) -> None:
        if result is None or isinstance(result, DurationChoiceCancelled):
            return
        if isinstance(result, KeepCurrentWindow):
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
        self._override_write_label = self._pending_override_label()
        self._override_write_keep = self._pending_model_target_keep
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
        target_label = self._override_write_label
        keep = self._override_write_keep
        result = self._override_write_result
        self._override_worker = None
        self._override_write_alias = ""
        self._override_write_label = ""
        self._override_write_keep = ""
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
        if override.effort:
            label = f"{label}@{override.effort}"
        if isinstance(result, ResolvedOverrideUntil):
            suffix = f"until {result.notification_display}"
        elif isinstance(result, OverrideUntilCleared):
            suffix = "until cleared"
        elif isinstance(result, RelativeOverrideDuration):
            suffix = f"for {format_duration_chosen(result.seconds)}"
        else:
            self.notify("Could not set override: invalid result", severity="error")
            return
        self.notify(f"{target_label} override: {label} {suffix}")
        self._mark_changed()
        self._refresh_rows(keep=keep or alias)

    def _on_clear_worker(self, event: Worker.StateChanged) -> None:
        if event.state not in (WorkerState.SUCCESS, WorkerState.ERROR):
            return
        alias = self._clear_write_alias
        label = self._clear_write_label
        keep = self._clear_write_keep
        self._clear_worker = None
        self._clear_write_alias = ""
        self._clear_write_label = ""
        self._clear_write_keep = ""
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
            self.notify(f"No active override on {label}", severity="warning")
            self._refresh_rows(keep=keep or alias)
            return
        self.notify(f"Cleared override on {label}")
        self._mark_changed()
        self._refresh_rows(keep=keep or alias)
