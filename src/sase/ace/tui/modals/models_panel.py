"""The Models panel — view every model alias and manage temporary overrides.

A leader-mode (``,m`` by default) surface that lists every configured and
implicit model alias (``default`` / ``coder`` / ``<provider>_coder`` /
``epic_creator`` / ``epic_lander`` / ``phase_worker`` plus any user-defined
``llm_provider.model_aliases.custom`` entry) with its effective provider/model,
its provenance, and any active temporary override.

From the selected row the user can set/change a time-bound temporary override
(**o**) or clear one (**x**) for *that alias* — reusing the shared model picker,
custom-model input, and duration picker. The ``default`` alias keeps its existing
behavior: an override on it drives the no-``%model`` launch default and the gold
top-bar pill (see :class:`sase.ace.tui.widgets.LLMOverrideIndicator`).

The user can also change an alias's *persistent* configured value with **e**
(Edit) or unset it back to the implicit fallback with **r** (Reset). Both go
through the Rust-backed, source-preserving config-edit path
(:mod:`sase.config.edit`), preview the diff before writing
(:class:`sase.ace.tui.modals.models_panel_edit.AliasEditPreviewModal`), and then
offer a ``use_chezmoi``-aware commit+push. Temporary-override state lives in
``~/.sase/llm_override.json`` (see :mod:`sase.llm_provider.temporary_override`).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.config import ConfigEditOp
from sase.llm_provider import (
    AliasView,
    build_alias_views,
    clear_alias_override,
    set_alias_override,
)
from sase.llm_provider.registry import format_provider_model_label

from .base import OptionListNavigationMixin
from .custom_model_input_modal import CustomModelInputModal
from .duration_choice_modal import (
    DURATION_CHOICE_CANCELLED,
    DurationChoiceCancelled,
)
from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from .models_panel_duration import (
    DurationPickerModal as _DurationPickerModal,
    format_duration_chosen as _format_duration_chosen,
    format_remaining as _format_remaining,
    now as _now,
)
from .models_panel_edit import AliasEditPreviewModal
from .models_panel_edit_helpers import (
    AliasCommitOffer,
    AliasEditOutcome,
    alias_model_edit_path,
    alias_reset_path,
    build_alias_commit_offer,
)
from .models_panel_rendering import (
    PROVIDER_MODEL_CELL_MAX as _PROVIDER_MODEL_CELL_MAX,
    description_text_for_view as _description_text_for_view,
    kind_label as _kind_label,
    provider_model_column_width as _provider_model_column_width,
    render_alias_row as _render_alias_row,
    state_tag as _state_tag,
)
from .models_panel_types import ModelsPanelResult

_LEGACY_TEST_EXPORTS = (
    DURATION_CHOICE_CANCELLED,
    _PROVIDER_MODEL_CELL_MAX,
    _format_remaining,
    _kind_label,
    _state_tag,
)

# ---------------------------------------------------------------------------
# Models panel
# ---------------------------------------------------------------------------


class ModelsPanel(OptionListNavigationMixin, ModalScreen[ModelsPanelResult]):
    """View every model alias and set/clear per-alias temporary overrides.

    Dismisses with a :class:`ModelsPanelResult` whose ``changed`` flag reports
    whether any override was written while the panel was open.
    """

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
        ("o", "override", "Override"),
        ("x", "clear", "Clear"),
        ("e", "edit", "Edit"),
        ("r", "reset", "Reset"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._changed = False
        self._views: list[AliasView] = []
        self._view_by_name: dict[str, AliasView] = {}
        self._pending_alias = ""
        self._pending_raw_model = ""
        self._pending_edit_view: AliasView | None = None

    # -- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="models-panel-container"):
            yield Static("[bold cyan]Models[/bold cyan]", id="models-panel-title")
            yield OptionList(*self._build_options(), id="models-panel-list")
            yield Static("", id="models-panel-description")
            yield Static(self._footer_markup(), id="models-panel-footer")

    def on_mount(self) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        option_list.focus()
        if option_list.option_count and option_list.highlighted is None:
            option_list.highlighted = 0
        self._update_description_strip()

    @staticmethod
    def _footer_markup() -> str:
        return (
            "[green]o[/green]=Override  "
            "[green]x[/green]=Clear  "
            "[green]e[/green]=Edit  "
            "[green]r[/green]=Reset  "
            "[dim]j/k[/dim]=Navigate  "
            "[dim]esc[/dim]=Close"
        )

    # -- option building -----------------------------------------------

    def _build_options(self) -> list[Option]:
        now = _now()
        self._views = build_alias_views()
        self._view_by_name = {view.name: view for view in self._views}
        provider_model_width = _provider_model_column_width(self._views)
        return [
            Option(
                _render_alias_row(
                    view, now=now, provider_model_width=provider_model_width
                ),
                id=view.name,
            )
            for view in self._views
        ]

    def _refresh_rows(self, *, keep: str | None = None) -> None:
        """Rebuild the list in place, preserving the highlighted alias."""
        option_list = self.query_one("#models-panel-list", OptionList)
        preferred = keep or self._highlighted_alias()
        option_list.clear_options()
        option_list.add_options(self._build_options())
        if preferred is not None:
            try:
                option_list.highlighted = option_list.get_option_index(preferred)
                self._update_description_strip()
                return
            except Exception:
                pass
        if option_list.option_count:
            option_list.highlighted = 0
        self._update_description_strip()

    def _update_description_strip(self) -> None:
        """Refresh the description strip for the currently highlighted alias."""
        try:
            description = self.query_one("#models-panel-description", Static)
        except Exception:
            return
        description.update(_description_text_for_view(self._selected_view()))

    def _highlighted_alias(self) -> str | None:
        option_list = self.query_one("#models-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _selected_view(self) -> AliasView | None:
        alias = self._highlighted_alias()
        if alias is None:
            return None
        return self._view_by_name.get(alias)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option is not None and event.option.id is not None:
            view = self._view_by_name.get(str(event.option.id))
            try:
                self.query_one("#models-panel-description", Static).update(
                    _description_text_for_view(view)
                )
            except Exception:
                pass

    # -- actions --------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(ModelsPanelResult(changed=self._changed))

    def action_cancel(self) -> None:
        """Alias for :meth:`action_close` (overrides the navigation mixin)."""
        self.action_close()

    def action_override(self) -> None:
        view = self._selected_view()
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
        view = self._selected_view()
        if view is None:
            return
        if view.override is None:
            self.notify(f"No active override on @{view.name}", severity="warning")
            return
        clear_alias_override(view.name)
        self.notify(f"Cleared override on @{view.name}")
        self._changed = True
        self._refresh_rows(keep=view.name)

    # -- override flow callbacks ---------------------------------------

    def _on_model_picked(self, result: str | None) -> None:
        if result is None:
            # Picker cancelled — keep the panel open so the user can retry.
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
        self.app.push_screen(_DurationPickerModal(), callback=self._on_duration_picked)

    def _on_duration_picked(
        self, result: float | None | DurationChoiceCancelled
    ) -> None:
        # The duration modal uses a sentinel for cancel so ``None`` stays a real
        # value ("until cleared").
        if isinstance(result, DurationChoiceCancelled):
            return
        seconds: float | None = result
        alias = self._pending_alias
        try:
            override = set_alias_override(
                alias,
                self._pending_raw_model,
                seconds,
                source="ace",
            )
        except ValueError as exc:
            self.notify(f"Invalid override: {exc}", severity="error")
            return
        label = format_provider_model_label(override.provider, override.model)
        self.notify(
            f"@{alias} override: {label} for {_format_duration_chosen(seconds)}"
        )
        self._changed = True
        self._refresh_rows(keep=alias)

    # -- persistent edit / reset ---------------------------------------

    def action_edit(self) -> None:
        view = self._selected_view()
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
        view = self._selected_view()
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
        # A persistent edit does not touch temporary overrides, so ``_changed``
        # (which drives the override indicators) stays as-is; refresh the rows
        # so the configured/effective columns reflect the new value.
        self._refresh_rows(keep=outcome.alias)
        self._offer_commit_push(outcome)

    def _offer_commit_push(self, outcome: AliasEditOutcome) -> None:
        offer = build_alias_commit_offer(
            outcome.applied.path,
            op=outcome.applied.op,
            alias=outcome.alias,
        )
        if offer is None:
            # Not in a git repo (or no pending change) — the file is already
            # written, so just confirm the save without a commit offer.
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

    # -- enter on the list selects override ----------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_override()
