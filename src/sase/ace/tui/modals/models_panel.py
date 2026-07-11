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

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.worker import Worker, WorkerState
from textual.widgets import OptionList, Static
from textual.widgets._option_list import Option

from sase.config import ConfigEditOp
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
    OpenOverrideUntil,
    OverrideDurationResult,
    OverrideUntilCleared,
    RelativeOverrideDuration,
    format_duration_chosen as _format_duration_chosen,
    format_remaining as _format_remaining,
    now as _now,
)
from .models_panel_time import (
    OverrideUntilBack,
    OverrideUntilModal,
    ResolvedOverrideUntil,
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
    description_text_for_row as _description_text_for_row,
    description_text_for_view as _description_text_for_view,
    kind_label as _kind_label,
    provider_model_column_width as _provider_model_column_width,
    render_alias_row as _render_alias_row,
    render_bucket_row as _render_bucket_row,
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

    # -- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="models-panel-container"):
            yield Static(self._title_text(), id="models-panel-title")
            yield OptionList(*self._build_options(), id="models-panel-list")
            yield Static("", id="models-panel-description")
            yield Static("", id="models-panel-footer")

    def on_mount(self) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        option_list.focus()
        if option_list.option_count and option_list.highlighted is None:
            self._set_highlighted_index(option_list, 0)
        self._update_context()

    def _footer_markup(self) -> str:
        row = self._selected_row()
        if self._active_bucket is None and isinstance(row, BucketView):
            return (
                "[green]l/enter[/green]=Open  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]esc[/dim]=Close"
            )
        footer = (
            "[green]o[/green]=Override  "
            "[green]x[/green]=Clear  "
            "[green]e[/green]=Edit  "
            "[green]r[/green]=Reset"
        )
        if self._active_bucket is not None:
            footer += "  [green]h[/green]=Back"
        return footer + ("  [dim]j/k[/dim]=Navigate  [dim]esc[/dim]=Close")

    def _title_text(self) -> Text:
        text = Text("Models", style="bold cyan")
        if self._active_bucket is not None:
            text.append(" › ", style="dim")
            text.append(self._active_bucket, style="bold #FFD787")
        return text

    # -- option building -----------------------------------------------

    def _build_options(self) -> list[Option]:
        self._views = build_alias_views()
        self._top_rows = build_models_panel_rows(self._views)
        self._bucket_by_name = {
            row.name: row for row in self._top_rows if isinstance(row, BucketView)
        }
        if (
            self._active_bucket is not None
            and self._active_bucket not in self._bucket_by_name
        ):
            self._active_bucket = None
        return self._render_current_options()

    @staticmethod
    def _row_id(row: AliasView | BucketView) -> str:
        if isinstance(row, BucketView):
            return f"bucket:{row.name}"
        return row.name

    def _current_rows(self) -> list[AliasView | BucketView]:
        if self._active_bucket is None:
            return self._top_rows
        bucket = self._bucket_by_name.get(self._active_bucket)
        return list(bucket.members) if bucket is not None else []

    def _render_current_options(self) -> list[Option]:
        rows = self._current_rows()
        alias_rows = [row for row in rows if isinstance(row, AliasView)]
        provider_model_width = _provider_model_column_width(alias_rows)
        now = _now()
        self._row_by_id = {self._row_id(row): row for row in rows}
        options: list[Option] = []
        for row in rows:
            row_id = self._row_id(row)
            if isinstance(row, BucketView):
                prompt = _render_bucket_row(
                    row, provider_model_width=provider_model_width
                )
            else:
                prompt = _render_alias_row(
                    row, now=now, provider_model_width=provider_model_width
                )
            options.append(Option(prompt, id=row_id))
        return options

    def _set_highlighted_index(
        self, option_list: OptionList, index: int | None
    ) -> None:
        self._updating_highlight = True
        try:
            option_list.highlighted = index
        finally:
            self._updating_highlight = False

    def _replace_display(self, *, keep: str | None = None) -> None:
        option_list = self.query_one("#models-panel-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._render_current_options())
        self._restore_highlight(option_list, keep)
        self._update_context()

    def _restore_highlight(
        self, option_list: OptionList, preferred: str | None
    ) -> None:
        if preferred is not None:
            try:
                index = option_list.get_option_index(preferred)
                self._set_highlighted_index(option_list, index)
                return
            except Exception:
                pass
        self._set_highlighted_index(
            option_list, 0 if option_list.option_count else None
        )

    def _refresh_rows(self, *, keep: str | None = None) -> None:
        """Reload and rebuild rows, preserving the highlighted row when possible."""
        option_list = self.query_one("#models-panel-list", OptionList)
        preferred = keep or self._highlighted_row_id()
        option_list.clear_options()
        option_list.add_options(self._build_options())
        self._restore_highlight(option_list, preferred)
        self._update_context()

    def _update_context(self) -> None:
        """Refresh the title, description strip, and context-aware footer."""
        try:
            self.query_one("#models-panel-title", Static).update(self._title_text())
            self.query_one("#models-panel-footer", Static).update(self._footer_markup())
        except Exception:
            pass
        self._update_description_strip()

    def _update_description_strip(self) -> None:
        """Refresh the description strip for the currently highlighted row."""
        try:
            description = self.query_one("#models-panel-description", Static)
        except Exception:
            return
        description.update(_description_text_for_row(self._selected_row()))

    def _highlighted_row_id(self) -> str | None:
        option_list = self.query_one("#models-panel-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    def _selected_row(self) -> AliasView | BucketView | None:
        row_id = self._highlighted_row_id()
        if row_id is None:
            return None
        return self._row_by_id.get(row_id)

    def _selected_alias(self) -> AliasView | None:
        row = self._selected_row()
        if isinstance(row, BucketView):
            self.notify("Press `l`/`enter` to open this bucket")
            return None
        return row

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if self._updating_highlight:
            return
        if event.option is not None and event.option.id is not None:
            row = self._row_by_id.get(str(event.option.id))
            try:
                self.query_one("#models-panel-description", Static).update(
                    _description_text_for_row(row)
                )
                self.query_one("#models-panel-footer", Static).update(
                    self._footer_markup()
                )
            except Exception:
                pass

    # -- actions --------------------------------------------------------

    def action_close(self) -> None:
        if self._override_worker is not None or self._clear_worker is not None:
            self.notify("An override update is still in progress.", severity="warning")
            return
        self.dismiss(ModelsPanelResult(changed=self._changed))

    def action_cancel(self) -> None:
        """Alias for :meth:`action_close` (overrides the navigation mixin)."""
        self.action_close()

    def action_enter_bucket(self) -> None:
        """Drill into the highlighted top-level bucket."""
        if self._active_bucket is not None:
            return
        row = self._selected_row()
        if not isinstance(row, BucketView):
            return
        self._active_bucket = row.name
        first = row.members[0].name if row.members else None
        self._replace_display(keep=first)

    def action_leave_bucket(self) -> None:
        """Return to the top-level rows and restore the source bucket cursor."""
        bucket = self._active_bucket
        if bucket is None:
            return
        self._active_bucket = None
        self._replace_display(keep=f"bucket:{bucket}")

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
                return clear_alias_override(alias), None
            except Exception as exc:
                return None, str(exc)

        self._clear_write_alias = alias
        self._clear_worker = self.run_worker(task, thread=True, exclusive=True)

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
                        set_alias_override_until(
                            alias,
                            raw_model,
                            result.expires_at,
                            source="ace",
                        ),
                        None,
                    )
                seconds = (
                    result.seconds
                    if isinstance(result, RelativeOverrideDuration)
                    else None
                )
                return (
                    set_alias_override(
                        alias,
                        raw_model,
                        seconds,
                        source="ace",
                    ),
                    None,
                )
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
            suffix = f"for {_format_duration_chosen(result.seconds)}"
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

    # -- persistent edit / reset ---------------------------------------

    def action_edit(self) -> None:
        view = self._selected_alias()
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
        if isinstance(self._selected_row(), BucketView):
            self.action_enter_bucket()
        else:
            self.action_override()
