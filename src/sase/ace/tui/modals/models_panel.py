"""The Models panel — view model aliases and manage their overrides.

This module is the stable public facade for the panel. Display and navigation,
temporary overrides, and persistent alias edits live in focused mixin modules.
Legacy helper exports remain here for callers and tests that imported them from
the original single-file implementation.
"""

from __future__ import annotations

from textual.screen import ModalScreen
from textual.worker import Worker

from .config_commit import ConfigCommitOffer
from sase.config import (
    DEFAULT_MAX_RUNNING_AGENTS,
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
    clear_runner_limit_override,
    get_active_runner_limit_override,
    get_configured_max_running_agents,
    get_use_chezmoi,
    set_runner_limit_override,
    set_runner_limit_override_until,
)
from sase.llm_provider import (
    AliasView,
    BucketView,
    EffectiveDefaultEffortSnapshot,
    TemporaryLLMOverride,
    TemporaryEffortOverride,
    build_alias_views,
    build_models_panel_rows,
    clear_alias_override,
    default_reasoning_effort,
    get_active_effort_override,
    clear_effort_override,
    set_effort_override,
    set_effort_override_until,
    set_alias_override,
    set_alias_override_until,
)

from .base import OptionListNavigationMixin
from .duration_choice_modal import DURATION_CHOICE_CANCELLED
from .models_panel_alias_edit import ModelsPanelAliasEditMixin
from .models_panel_display import ModelsPanelDisplayMixin
from .models_panel_effort import ModelsPanelEffortMixin
from .models_panel_effort_edit import build_default_effort_commit_offer
from .models_panel_duration import (
    DurationPickerModal as _DurationPickerModal,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen as _format_duration_chosen,
    format_remaining as _format_remaining,
    now as _now,
)
from .models_panel_edit_helpers import (
    AliasCommitOffer,
    build_alias_commit_offer,
    build_model_setting_commit_offer,
)
from .models_panel_override import ModelsPanelOverrideMixin
from .models_panel_providers import ModelsPanelProvidersMixin
from .models_panel_runner_limit import ModelsPanelRunnerLimitMixin
from .models_panel_runner_limit_edit import build_runner_limit_commit_offer
from .models_panel_threshold import ModelsPanelThresholdMixin
from .models_panel_threshold_edit import (
    build_big_epic_phase_threshold_commit_offer,
)
from .model_picker_modal import AliasSelectionContext
from .models_panel_rendering import (
    PROVIDER_MODEL_CELL_MAX as _PROVIDER_MODEL_CELL_MAX,
    description_text_for_view as _description_text_for_view,
    kind_label as _kind_label,
    provider_model_column_width as _provider_model_column_width,
    render_alias_row as _render_alias_row,
    render_bucket_row as _render_bucket_row,
    state_tag as _state_tag,
)
from .models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    DefaultEffortSettingRow,
    LaunchModelSettingRow,
    ModelsPanelDisplayRow,
    RunnerLimitSettingRow,
)
from .models_panel_time import ResolvedOverrideUntil
from .models_panel_types import ModelsPanelResult

_LEGACY_TEST_EXPORTS = (
    DURATION_CHOICE_CANCELLED,
    _PROVIDER_MODEL_CELL_MAX,
    _format_remaining,
    _kind_label,
    _state_tag,
)


class ModelsPanel(
    ModelsPanelDisplayMixin,
    ModelsPanelRunnerLimitMixin,
    ModelsPanelEffortMixin,
    ModelsPanelProvidersMixin,
    ModelsPanelOverrideMixin,
    ModelsPanelThresholdMixin,
    ModelsPanelAliasEditMixin,
    OptionListNavigationMixin,
    ModalScreen[ModelsPanelResult],
):
    """View model aliases and manage temporary or persistent values."""

    _option_list_id = "models-panel-list"

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("l", "enter_bucket", "Open bucket"),
        ("right", "enter_bucket", "Open bucket"),
        ("h", "leave_bucket", "Back"),
        ("left", "leave_bucket", "Back"),
        ("o", "override", "Override"),
        ("x", "clear", "Clear"),
        ("e", "edit", "Edit"),
        ("r", "reset", "Reset"),
        ("ctrl+e", "manage_default_effort", "Effort"),
        ("ctrl+r", "manage_runner_limit", "Limit"),
        ("p", "providers", "Providers"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._changed = False
        self._default_effort: str | None = None
        self._effort_snapshot = EffectiveDefaultEffortSnapshot(
            configured_effort=None,
            temporary_override=None,
            captured_at=_now(),
        )
        self._effort_uses_chezmoi = False
        self._runner_limit_snapshot = EffectiveRunnerLimitSnapshot(
            configured_limit=DEFAULT_MAX_RUNNING_AGENTS,
            temporary_override=None,
            captured_at=_now(),
        )
        self._runner_limit_uses_chezmoi = False
        self._provider_snapshot = self._initial_provider_snapshot()
        self._provider_disables = {}
        self._provider_statuses = ()
        self._provider_snapshot_worker = None
        self._provider_snapshot_keep = None
        self._provider_snapshot_signal_changes = False
        self._provider_snapshot_update_rows = False
        self._provider_routing_changed = False
        self._launch_model_rows: tuple[
            LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...
        ] = self._provider_snapshot.launch_model_rows
        self._views: list[AliasView] = []
        self._top_rows: list[ModelsPanelDisplayRow] = []
        self._bucket_by_name: dict[str, BucketView] = {}
        self._row_by_id: dict[str, ModelsPanelDisplayRow] = {}
        self._active_bucket: str | None = None
        self._updating_highlight = False
        self._warning_toast_emitted = False
        self._pending_alias = ""
        self._pending_model_target_label = ""
        self._pending_model_target_keep = ""
        self._pending_raw_model = ""
        self._pending_edit_raw_model = ""
        self._pending_edit_view: AliasView | LaunchModelSettingRow | None = None
        self._pending_edit_target_label = ""
        self._pending_edit_target_kind = "Model Alias"
        self._pending_edit_keep = ""
        self._pending_edit_is_model_setting = False
        self._pending_alias_selection: AliasSelectionContext | None = None
        self._override_worker: (
            Worker[tuple[TemporaryLLMOverride | None, str | None]] | None
        ) = None
        self._clear_worker: Worker[tuple[bool | None, str | None]] | None = None
        self._config_commit_offer_worker: Worker[AliasCommitOffer | None] | None = None
        self._effort_snapshot_worker: (
            Worker[tuple[EffectiveDefaultEffortSnapshot, bool]] | None
        ) = None
        self._effort_override_worker: (
            Worker[tuple[TemporaryEffortOverride | None, str | None]] | None
        ) = None
        self._effort_clear_worker: Worker[tuple[bool | None, str | None]] | None = None
        self._effort_commit_offer_worker: Worker[AliasCommitOffer | None] | None = None
        self._runner_limit_snapshot_worker: (
            Worker[tuple[EffectiveRunnerLimitSnapshot, bool]] | None
        ) = None
        self._runner_limit_override_worker: (
            Worker[tuple[TemporaryRunnerLimitOverride | None, str | None]] | None
        ) = None
        self._runner_limit_clear_worker: (
            Worker[tuple[bool | None, str | None]] | None
        ) = None
        self._runner_limit_commit_offer_worker: (
            Worker[AliasCommitOffer | None] | None
        ) = None
        self._threshold_commit_offer_worker: Worker[ConfigCommitOffer | None] | None = (
            None
        )
        self._runner_limit_write_value: int | None = None
        self._runner_limit_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        ) = None
        self._effort_write_level: str | None = None
        self._effort_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        ) = None
        self._override_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        ) = None
        self._override_write_alias = ""
        self._override_write_label = ""
        self._override_write_keep = ""
        self._clear_write_alias = ""
        self._clear_write_label = ""
        self._clear_write_keep = ""

    # These indirections deliberately resolve dependencies from this facade.
    # Besides keeping the mixins small, they preserve existing monkeypatch
    # points for downstream callers that imported the former monolithic module.

    def _load_alias_views(self) -> list[AliasView]:
        return build_alias_views(
            now=self._models_panel_now(),
            provider_disables=self._provider_disables,
        )

    def _load_default_reasoning_effort(self) -> str | None:
        return default_reasoning_effort()

    def _load_effective_effort_snapshot(
        self,
    ) -> tuple[EffectiveDefaultEffortSnapshot, bool]:
        captured_at = max(self._models_panel_now(), 0.000001)
        return (
            EffectiveDefaultEffortSnapshot(
                configured_effort=self._load_default_reasoning_effort(),
                temporary_override=get_active_effort_override(captured_at),
                captured_at=captured_at,
            ),
            get_use_chezmoi(),
        )

    def _load_models_panel_rows(
        self, views: list[AliasView]
    ) -> list[ModelsPanelDisplayRow]:
        return [
            *self._launch_model_rows,
            DefaultEffortSettingRow(self._effort_snapshot),
            RunnerLimitSettingRow(self._runner_limit_snapshot),
            *build_models_panel_rows(views),
        ]

    def _load_effective_runner_limit_snapshot(
        self,
    ) -> tuple[EffectiveRunnerLimitSnapshot, bool]:
        captured_at = max(self._models_panel_now(), 0.000001)
        return (
            EffectiveRunnerLimitSnapshot(
                configured_limit=get_configured_max_running_agents(),
                temporary_override=get_active_runner_limit_override(captured_at),
                captured_at=captured_at,
            ),
            get_use_chezmoi(),
        )

    def _models_panel_now(self) -> float:
        return _now()

    def _clear_alias_override(self, alias: str) -> bool:
        return clear_alias_override(alias)

    def _set_alias_override(
        self, alias: str, raw_model: str, seconds: float | None
    ) -> TemporaryLLMOverride:
        return set_alias_override(alias, raw_model, seconds, source="ace")

    def _set_alias_override_until(
        self, alias: str, raw_model: str, expires_at: float
    ) -> TemporaryLLMOverride:
        return set_alias_override_until(alias, raw_model, expires_at, source="ace")

    def _set_default_effort_override(
        self, effort: str, seconds: float | None
    ) -> TemporaryEffortOverride:
        return set_effort_override(
            effort,
            seconds,
            source="ace",
            now=self._models_panel_now(),
        )

    def _set_default_effort_override_until(
        self, effort: str, expires_at: float
    ) -> TemporaryEffortOverride:
        return set_effort_override_until(
            effort,
            expires_at,
            source="ace",
            now=self._models_panel_now(),
        )

    def _clear_default_effort_override(self) -> bool:
        return clear_effort_override()

    def _set_runner_limit_override(
        self, limit: int, seconds: float | None
    ) -> TemporaryRunnerLimitOverride:
        return set_runner_limit_override(
            limit,
            seconds,
            source="ace",
            now=self._models_panel_now(),
        )

    def _set_runner_limit_override_until(
        self, limit: int, expires_at: float
    ) -> TemporaryRunnerLimitOverride:
        return set_runner_limit_override_until(
            limit,
            expires_at,
            source="ace",
            now=self._models_panel_now(),
        )

    def _clear_runner_limit_override(self) -> bool:
        return clear_runner_limit_override()

    def _build_alias_commit_offer(
        self, path: str, *, op: str, alias: str
    ) -> AliasCommitOffer | None:
        return build_alias_commit_offer(path, op=op, alias=alias)

    def _build_model_setting_commit_offer(
        self, path: str, *, op: str, label: str
    ) -> AliasCommitOffer | None:
        return build_model_setting_commit_offer(path, op=op, label=label)

    def _build_default_effort_commit_offer(self, path: str) -> AliasCommitOffer | None:
        return build_default_effort_commit_offer(path)

    def _build_runner_limit_commit_offer(self, path: str) -> AliasCommitOffer | None:
        return build_runner_limit_commit_offer(path)

    def _build_big_epic_phase_threshold_commit_offer(
        self, path: str
    ) -> ConfigCommitOffer | None:
        return build_big_epic_phase_threshold_commit_offer(path)

    def _request_agents_refresh(self, source: str) -> None:
        request_refresh = getattr(self.app, "request_agents_refresh", None)
        if callable(request_refresh):
            request_refresh(source)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if self._on_provider_snapshot_worker_state(event):
            return
        if self._on_config_commit_offer_worker_state(event):
            return
        if self._on_effort_worker_state_changed(event):
            return
        if self._on_runner_limit_worker_state_changed(event):
            return
        if self._on_threshold_worker_state_changed(event):
            return
        ModelsPanelOverrideMixin.on_worker_state_changed(self, event)

    def on_unmount(self) -> None:
        self._cancel_config_commit_offer()
        self._cancel_effort_workers()
        self._cancel_runner_limit_workers()
        self._cancel_threshold_workers()
        self._cancel_provider_workers()
        for worker in (self._override_worker, self._clear_worker):
            if worker is not None and not worker.is_finished:
                worker.cancel()
