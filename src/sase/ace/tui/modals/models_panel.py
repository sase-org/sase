"""The Models panel — view model aliases and manage their overrides.

This module is the stable public facade for the panel. Display and navigation,
temporary overrides, and persistent alias edits live in focused mixin modules.
Legacy helper exports remain here for callers and tests that imported them from
the original single-file implementation.
"""

from __future__ import annotations

from textual.screen import ModalScreen
from textual.worker import Worker

from sase.llm_provider import (
    AliasView,
    BucketView,
    TemporaryLLMOverride,
    build_alias_views,
    build_models_panel_rows,
    clear_alias_override,
    set_alias_override,
    set_alias_override_until,
)

from .base import OptionListNavigationMixin
from .duration_choice_modal import DURATION_CHOICE_CANCELLED
from .models_panel_alias_edit import ModelsPanelAliasEditMixin
from .models_panel_display import ModelsPanelDisplayMixin
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
)
from .models_panel_override import ModelsPanelOverrideMixin
from .models_panel_rendering import (
    PROVIDER_MODEL_CELL_MAX as _PROVIDER_MODEL_CELL_MAX,
    description_text_for_view as _description_text_for_view,
    kind_label as _kind_label,
    provider_model_column_width as _provider_model_column_width,
    render_alias_row as _render_alias_row,
    render_bucket_row as _render_bucket_row,
    state_tag as _state_tag,
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
    ModelsPanelOverrideMixin,
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
    ]

    def __init__(self) -> None:
        super().__init__()
        self._changed = False
        self._views: list[AliasView] = []
        self._top_rows: list[AliasView | BucketView] = []
        self._bucket_by_name: dict[str, BucketView] = {}
        self._row_by_id: dict[str, AliasView | BucketView] = {}
        self._active_bucket: str | None = None
        self._updating_highlight = False
        self._pending_alias = ""
        self._pending_raw_model = ""
        self._pending_edit_view: AliasView | None = None
        self._override_worker: (
            Worker[tuple[TemporaryLLMOverride | None, str | None]] | None
        ) = None
        self._clear_worker: Worker[tuple[bool | None, str | None]] | None = None
        self._override_write_result: (
            RelativeOverrideDuration
            | OverrideUntilCleared
            | ResolvedOverrideUntil
            | None
        ) = None
        self._override_write_alias = ""
        self._clear_write_alias = ""

    # These indirections deliberately resolve dependencies from this facade.
    # Besides keeping the mixins small, they preserve existing monkeypatch
    # points for downstream callers that imported the former monolithic module.

    def _load_alias_views(self) -> list[AliasView]:
        return build_alias_views()

    def _load_models_panel_rows(
        self, views: list[AliasView]
    ) -> list[AliasView | BucketView]:
        return build_models_panel_rows(views)

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

    def _build_alias_commit_offer(
        self, path: str, *, op: str, alias: str
    ) -> AliasCommitOffer | None:
        return build_alias_commit_offer(path, op=op, alias=alias)
