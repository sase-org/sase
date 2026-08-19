"""Persistent alias-edit and commit workflow for the Models panel."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.worker import Worker, WorkerState

from sase.config import ConfigEditOp
from sase.llm_provider import (
    AliasView,
    EffectiveDefaultEffortSnapshot,
    TemporaryProviderDisable,
)
from sase.llm_provider.config import validate_model_alias_selector_value
from sase.llm_provider.load_balancing import concatenated_selector_members
from sase.xprompt.effort import split_model_effort

from .config_commit import push_config_commit_prompt, submit_config_commit_task
from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import (
    CUSTOM_SENTINEL,
    SELECTOR_SENTINEL,
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
from .models_panel_effort_cards import (
    DefaultEffortAction,
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
    DefaultEffortPickerMode,
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
from .models_panel_selector import member_rejection, parse_selector_for_display
from .models_panel_selector_builder import SelectorBuilderModal

if TYPE_CHECKING:
    from textual.screen import ModalScreen as _MixinBase
else:
    _MixinBase = object


class ModelsPanelAliasEditMixin(_MixinBase):
    """Edit persistent alias values and optionally commit the resulting file."""

    if TYPE_CHECKING:
        _pending_edit_view: AliasView | LaunchModelSettingRow | None
        _pending_edit_raw_model: str
        _pending_edit_target_kind: str
        _pending_edit_target_label: str
        _pending_edit_keep: str
        _pending_edit_is_model_setting: bool
        _pending_alias_selection: AliasSelectionContext | None
        _config_commit_offer_worker: Worker[AliasCommitOffer | None] | None
        _views: list[AliasView]
        _effort_snapshot: EffectiveDefaultEffortSnapshot
        _provider_disables: dict[str, TemporaryProviderDisable]

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

        def _build_alias_commit_offer(
            self, path: str, *, op: str, alias: str
        ) -> AliasCommitOffer | None: ...

        def _build_model_setting_commit_offer(
            self, path: str, *, op: str, label: str
        ) -> AliasCommitOffer | None: ...

        def _on_default_effort_action(
            self, result: DefaultEffortAction | None
        ) -> None: ...

        def _on_default_effort_level(
            self,
            mode: DefaultEffortPickerMode,
            result: DefaultEffortLevelChoice | None,
        ) -> None: ...

        def _on_runner_limit_action(self, result: RunnerLimitAction | None) -> None: ...

        def action_edit_big_epic_phase_threshold(self) -> None: ...

        def action_reset_big_epic_phase_threshold(self) -> None: ...

    def action_edit(self) -> None:
        selected = self._selected_row()
        if isinstance(selected, DefaultEffortSettingRow):
            self._on_default_effort_action("edit")
            return
        if isinstance(selected, RunnerLimitSettingRow):
            self._on_runner_limit_action("edit")
            return
        if isinstance(selected, BigEpicPhaseThresholdSettingRow):
            self.action_edit_big_epic_phase_threshold()
            return
        row = self._selected_model_row()
        if row is None:
            return
        self._prepare_pending_edit_target(row)
        self._pending_edit_raw_model = ""
        key = row.override_key if isinstance(row, LaunchModelSettingRow) else row.name
        self._pending_alias_selection = AliasSelectionContext(
            views=tuple(self._views),
            target_alias=key,
            operation="persistent",
        )
        self.app.push_screen(
            ModelPickerModal(
                title=f"Edit Model — {self._pending_edit_target_label}",
                include_default_option=False,
                alias_context=self._pending_alias_selection,
                include_selector_option=isinstance(row, AliasView),
                provider_disables=self._provider_disables,
            ),
            callback=self._on_edit_model_picked,
        )

    def action_reset(self) -> None:
        selected = self._selected_row()
        if isinstance(selected, DefaultEffortSettingRow):
            self._on_default_effort_level("edit", DefaultEffortLevelChoice(None))
            return
        if isinstance(selected, RunnerLimitSettingRow):
            self.notify("Use e to edit the running-agent limit", severity="warning")
            return
        if isinstance(selected, BigEpicPhaseThresholdSettingRow):
            self.action_reset_big_epic_phase_threshold()
            return
        row = self._selected_model_row()
        if row is None:
            return
        self._prepare_pending_edit_target(row)
        if isinstance(row, LaunchModelSettingRow):
            self._open_alias_preview(
                row.field,
                ConfigEditOp.unset(),
                path=row.config_path,
                action_label="Reset",
                target_kind="Model Setting",
                target_label=row.label,
            )
            return
        view = row
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
            target_kind="Model Alias",
            target_label=f"@{view.name}",
            reset_deletes_alias=(
                view.kind == "user" and view.configured_source == "custom"
            ),
        )

    def _prepare_pending_edit_target(
        self, row: AliasView | LaunchModelSettingRow
    ) -> None:
        self._pending_edit_view = row
        if isinstance(row, LaunchModelSettingRow):
            self._pending_edit_target_label = row.label
            self._pending_edit_target_kind = "Model Setting"
            self._pending_edit_keep = row.row_id
            self._pending_edit_is_model_setting = True
            return
        self._pending_edit_target_label = f"@{row.name}"
        self._pending_edit_target_kind = "Model Alias"
        self._pending_edit_keep = row.name
        self._pending_edit_is_model_setting = False

    def _pending_edit_label(self) -> str:
        """Return a human label for the pending edit target."""
        if self._pending_edit_target_label:
            return self._pending_edit_target_label
        view = self._pending_edit_view
        if isinstance(view, LaunchModelSettingRow):
            return view.label
        if isinstance(view, AliasView):
            return f"@{view.name}"
        return ""

    def _on_edit_model_picked(self, result: str | None) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        if result == SELECTOR_SENTINEL:
            selection = self._pending_alias_selection
            if selection is None or isinstance(view, LaunchModelSettingRow):
                return
            self.app.push_screen(
                SelectorBuilderModal(
                    alias=view.name,
                    current_value=view.raw_value or "",
                    alias_context=selection,
                    effort_snapshot=self._effort_snapshot,
                    now=self._models_panel_now(),
                    provider_disables=self._provider_disables,
                ),
                callback=self._on_selector_built,
            )
            return
        rejection = alias_reference_rejection(self._pending_alias_selection, result)
        if rejection is not None:
            self.notify(
                f"Cannot set {self._pending_edit_label()} to "
                f"{result.strip()}: {rejection}.",
                severity="warning",
            )
            return
        if result == CUSTOM_SENTINEL:
            self.app.push_screen(
                CustomModelInputModal(
                    title="Custom Alias Value",
                    hint=(
                        "Single values may end in @effort; selectors keep "
                        "per-member effort: A@low | B@high. "
                        "A | 3 B weights B three-to-one. "
                        "(A | B) || C is last-resort when the pool is unavailable"
                    ),
                    placeholder=("e.g. claude/fable || codex/gpt-5.6-sol"),
                    initial=view.raw_value or "",
                ),
                callback=self._on_edit_custom_picked,
            )
            return
        self._open_edit_model_effort_picker(result)

    def _on_edit_custom_picked(self, result: str | None) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        raw_model = result.strip()
        parsed = parse_selector_for_display(raw_model)
        if parsed.error is not None:
            self.notify(
                f"Cannot set {self._pending_edit_label()}: {parsed.error}",
                severity="warning",
            )
            return
        if parsed.selector is not None:
            for member in concatenated_selector_members(parsed.selector):
                disabled = disabled_explicit_provider_message(
                    member,
                    self._provider_disables,
                    now=self._models_panel_now(),
                )
                if disabled is not None:
                    self.notify(
                        f"Cannot set {self._pending_edit_label()} to "
                        f"{member}: {disabled}.",
                        severity="warning",
                    )
                    return
                note = soft_explicit_provider_note(
                    member,
                    self._provider_disables,
                    now=self._models_panel_now(),
                )
                if note is not None:
                    self.notify(note)
                rejection = member_rejection(self._pending_alias_selection, member)
                if rejection is not None:
                    self.notify(
                        f"Cannot set {self._pending_edit_label()} to "
                        f"{member}: {rejection}.",
                        severity="warning",
                    )
                    return
            self._pending_edit_raw_model = raw_model
            self._open_model_edit_preview(view, raw_model)
            return
        rejection = alias_reference_rejection(self._pending_alias_selection, raw_model)
        if rejection is not None:
            self.notify(
                f"Cannot set {self._pending_edit_label()} to {raw_model}: {rejection}.",
                severity="warning",
            )
            return
        disabled = disabled_explicit_provider_message(
            raw_model,
            self._provider_disables,
            now=self._models_panel_now(),
        )
        if disabled is not None:
            self.notify(
                f"Cannot set {self._pending_edit_label()} to {raw_model}: {disabled}.",
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
        if effort is not None:
            self._pending_edit_raw_model = raw_model
            self._open_model_edit_preview(view, raw_model)
            return
        self._open_edit_model_effort_picker(raw_model)

    def _open_edit_model_effort_picker(self, raw_model: str) -> None:
        self._pending_edit_raw_model = raw_model.strip()
        self.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                self._effort_snapshot,
                now=self._models_panel_now(),
                model=self._pending_edit_raw_model,
            ),
            callback=self._on_edit_model_effort_picked,
        )

    def _on_edit_model_effort_picked(
        self,
        result: DefaultEffortLevelChoice | None,
    ) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        raw_model = self._pending_edit_raw_model
        if result.effort is not None:
            raw_model = f"{raw_model}@{result.effort}"
        self._pending_edit_raw_model = raw_model
        self._open_model_edit_preview(view, raw_model)

    def _on_selector_built(self, result: str | None) -> None:
        if result is None:
            return
        view = self._pending_edit_view
        if view is None:
            return
        self._pending_edit_raw_model = result
        self._open_model_edit_preview(view, result)

    def _open_model_edit_preview(
        self, view: AliasView | LaunchModelSettingRow, model: str
    ) -> None:
        if isinstance(view, AliasView):
            selector_errors = validate_model_alias_selector_value(view.name, model)
            if selector_errors:
                self.notify(
                    f"Cannot set @{view.name}: {selector_errors[0]}",
                    severity="warning",
                )
                return
        self._open_alias_preview(
            view.field if isinstance(view, LaunchModelSettingRow) else view.name,
            ConfigEditOp.set_value(model),
            path=(
                alias_model_edit_path(
                    view.name,
                    kind=view.kind,
                    configured_source=view.configured_source,
                )
                if isinstance(view, AliasView)
                else view.config_path
            ),
            target_kind=self._pending_edit_target_kind,
            target_label=self._pending_edit_label(),
        )

    def _open_alias_preview(
        self,
        alias: str,
        op: ConfigEditOp,
        *,
        path: str | None = None,
        action_label: str | None = None,
        target_kind: str | None = None,
        target_label: str | None = None,
        reset_deletes_alias: bool = False,
    ) -> None:
        self.app.push_screen(
            AliasEditPreviewModal(
                alias,
                op,
                path=path,
                action_label=action_label,
                target_kind=target_kind or self._pending_edit_target_kind,
                target_label=target_label or self._pending_edit_label(),
                reset_deletes_alias=reset_deletes_alias,
            ),
            callback=self._on_alias_edited,
        )

    def _on_alias_edited(self, outcome: AliasEditOutcome | None) -> None:
        if outcome is None:
            return
        verb = "Reset" if outcome.applied.op == "unset" else "Updated"
        suffix = (
            f" to {self._pending_edit_raw_model}"
            if outcome.applied.op != "unset" and self._pending_edit_raw_model
            else ""
        )
        target_label = self._pending_edit_label() or f"@{outcome.alias}"
        self.notify(f"{verb} {target_label}{suffix}")
        # Persistent edits do not touch temporary overrides. Refresh the rows
        # so the configured/effective columns reflect the new value.
        self._refresh_rows(keep=self._pending_edit_keep or outcome.alias)
        self._offer_commit_push(outcome)

    def _offer_commit_push(self, outcome: AliasEditOutcome) -> None:
        worker = self._config_commit_offer_worker
        if worker is not None and not worker.is_finished:
            worker.cancel()
        path = outcome.applied.path
        op = outcome.applied.op
        alias = outcome.alias
        target_label = self._pending_edit_label() or f"@{alias}"
        is_model_setting = self._pending_edit_is_model_setting

        def task() -> AliasCommitOffer | None:
            if is_model_setting:
                return self._build_model_setting_commit_offer(
                    path, op=op, label=target_label
                )
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
            noun = (
                "model-setting"
                if self._pending_edit_is_model_setting
                else "model-alias"
            )
            push_config_commit_prompt(
                self.app,  # type: ignore[attr-defined]
                offer,
                message=f"Commit and push your {noun} change?",
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
            display_name=f"commit model config {offer.rel_path}",
        )
