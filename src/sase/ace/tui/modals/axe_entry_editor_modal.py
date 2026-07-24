"""Reusable AXE lumberjack/chop single-page property editor.

Integrations provide immutable seed data plus plan/apply callbacks; the modal
returns the successful write value and whether the caller should reconcile a
running AXE.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from textual import events
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from .axe_entry_editor_rendering import (
    AxeEntryEditorRenderingMixin,
    AxeValueInput,
    AxeValueTextArea,
)
from .axe_entry_editor_types import (
    AxeEntryEditorResult,
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeEntryKind,
    AxeEntryMutationRequest,
    AxeWritableScope,
    axe_entry_schema,
    build_axe_entry_form,
)
from .config_transaction import (
    ConfigTransactionApplyResult,
    ConfigTransactionControllerMixin,
    ConfigTransactionInputError,
    ConfigTransactionMetadata,
    ConfigTransactionRequest,
)
from .schema_object_form import SchemaObjectField, SchemaObjectForm


class AxeEntryEditorModal(
    AxeEntryEditorRenderingMixin,
    ConfigTransactionControllerMixin,
    ModalScreen[AxeEntryEditorResult | None],
):
    """Edit every lumberjack or base-chop property on one sparse sheet."""

    AUTO_FOCUS = None
    BINDINGS = [
        ("escape", "back", "Back/Cancel"),
        ("ctrl+s", "confirm", "Preview/Save"),
        ("enter", "edit_or_confirm", "Edit/Save"),
        ("i", "edit_field", "Edit"),
        ("ctrl+o", "save_only", "Save only"),
        ("j", "nav_down", "Down"),
        ("k", "nav_up", "Up"),
        ("down", "nav_down", "Down"),
        ("up", "nav_up", "Up"),
        ("h", "cycle_value(-1)", "Previous value"),
        ("left", "cycle_value(-1)", "Previous value"),
        ("l", "cycle_value(1)", "Next value"),
        ("right", "cycle_value(1)", "Next value"),
        ("ctrl+d", "preview_page_down", "Page Down"),
        ("ctrl+u", "preview_page_up", "Page Up"),
        ("g", "top_or_first", "First/Top"),
        ("G", "bottom_or_last", "Last/Bottom"),
        ("space", "toggle_value", "Toggle"),
        ("ctrl+t", "cycle_scope", "Scope"),
        ("ctrl+r", "toggle_reset", "Inherit/reset"),
        ("ctrl+l", "reload_transaction", "Reload"),
        Binding("1", "select_scope(1)", "Scope 1", show=False),
        Binding("2", "select_scope(2)", "Scope 2", show=False),
        Binding("3", "select_scope(3)", "Scope 3", show=False),
        Binding("4", "select_scope(4)", "Scope 4", show=False),
        Binding("5", "select_scope(5)", "Scope 5", show=False),
        Binding("6", "select_scope(6)", "Scope 6", show=False),
        Binding("7", "select_scope(7)", "Scope 7", show=False),
        Binding("8", "select_scope(8)", "Scope 8", show=False),
        Binding("9", "select_scope(9)", "Scope 9", show=False),
    ]

    def __init__(
        self,
        seed: AxeEntryEditorSeed,
        *,
        plan_callback: Callable[[AxeEntryMutationRequest], Any] | None = None,
        apply_callback: Callable[[Any], Any] | None = None,
        reload_callback: Callable[[], AxeEntryEditorSeed] | None = None,
        plan: Callable[[AxeEntryMutationRequest], Any] | None = None,
        apply: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__()
        self._seed = seed
        self._plan_entry = plan_callback or plan or self._missing_plan_callback
        self._apply_entry = apply_callback or apply or self._missing_apply_callback
        self._reload_entry = reload_callback
        self._stage: Literal["edit", "preview"] = "edit"
        self._mode: Literal["browse", "cell"] = "cell" if seed.new_entry else "browse"
        self._target = self._initial_target(seed)
        self._busy = False
        self._error: str | None = None
        self._status: str | None = None
        self._plan: Any = None
        self._restart_requested = False
        self._form = self._build_form(seed, target=self._target)
        self._active_name = self._form.fields[0].name if self._form.fields else None
        self._cell_editor: VimTextArea | None = None
        self._cell_generation = 0
        self._editor_mode_label = ""
        self._init_config_transaction(
            metadata=ConfigTransactionMetadata(
                title=(
                    f"Add AXE {seed.identity.kind}"
                    if seed.new_entry
                    else f"Edit AXE {seed.identity.kind}"
                ),
                identity=(
                    seed.identity.lumberjack,
                    *((seed.identity.chop,) if seed.identity.chop else ()),
                ),
                running=seed.running,
                generated_warning=seed.generated_warning,
            ),
            plan_callback=self._plan_transaction,
            apply_callback=self._apply_transaction,
            reload_callback=reload_callback,
        )

    @staticmethod
    def _missing_plan_callback(_request: AxeEntryMutationRequest) -> Any:
        raise RuntimeError("AXE editor requires a plan callback before preview")

    @staticmethod
    def _missing_apply_callback(_plan: Any) -> Any:
        raise RuntimeError("AXE editor requires an apply callback before save")

    @staticmethod
    def _initial_target(seed: AxeEntryEditorSeed) -> str | None:
        names = [scope.name for scope in seed.writable_scopes]
        if seed.initial_target in names:
            return seed.initial_target
        return names[0] if names else None

    @staticmethod
    def _build_form(
        seed: AxeEntryEditorSeed, *, target: str | None = None
    ) -> SchemaObjectForm:
        return build_axe_entry_form(seed, target=target)

    # -- property-sheet interaction ----------------------------------

    def _active_field(self) -> SchemaObjectField | None:
        if self._active_name is None:
            return None
        try:
            return self._form.field(self._active_name)
        except KeyError:
            return None

    def _mount_cell_editor(self, field: SchemaObjectField) -> None:
        if (
            not self.is_mounted
            or self._stage != "edit"
            or self._mode != "cell"
            or field.editor_kind in {"bool", "enum"}
        ):
            return
        current = self._cell_editor
        if (
            current is not None
            and current.is_mounted
            and getattr(current, "axe_field_name", None) == field.name
        ):
            self.call_after_refresh(
                lambda: self._focus_cell_editor(
                    current,
                    generation=self._cell_generation,
                )
            )
            return
        self._remove_cell_editor()
        text = self._field_editor_text(field)
        self._cell_generation += 1
        generation = self._cell_generation
        if field.editor_kind in {"int", "number", "string"}:
            editor: VimTextArea = AxeValueInput(
                text,
                field_name=field.name,
                generation=generation,
            )
        else:
            editor = AxeValueTextArea(
                text,
                field_name=field.name,
                value_kind=field.editor_kind,
                generation=generation,
            )
        self._cell_editor = editor
        index = self._field_index(field.name)
        if index is None:
            self._cell_editor = None
            return
        cell = self.query_one(f"#axe-editor-value-{index}", Container)
        cell.mount(editor)
        self._render_all()

    def _cell_editor_mounted(self, editor: VimTextArea) -> None:
        """Focus a newly mounted cell editor after its first layout refresh."""
        if editor is not self._cell_editor:
            return
        generation = self._cell_generation
        self.call_after_refresh(
            lambda: self._focus_cell_editor(editor, generation=generation)
        )

    def _focus_cell_editor(
        self,
        editor: VimTextArea,
        *,
        generation: int,
    ) -> None:
        if (
            not self.is_mounted
            or self._stage != "edit"
            or self._mode != "cell"
            or self._cell_editor is not editor
            or self._cell_generation != generation
            or not editor.is_mounted
        ):
            return
        self._scroll_active_row()
        editor.focus()
        if isinstance(editor, SingleLineVimTextArea):
            editor.select_all()
        editor._update_vim_mode_display()

    def _remove_cell_editor(self) -> None:
        editor = self._cell_editor
        if editor is None:
            return
        self.set_focus(None)
        self._cell_editor = None
        self._cell_generation += 1
        if editor.is_mounted:
            editor.remove()

    def _commit_cell(self) -> None:
        editor = self._cell_editor
        if editor is None:
            return
        name = getattr(editor, "axe_field_name", self._active_name)
        if name is None:
            return
        self._form = self._form.set_text(name, editor.text, live=False)
        self._error = None

    def _leave_cell(self, *, commit: bool = True) -> None:
        if self._mode != "cell":
            return
        if commit:
            self._commit_cell()
        self._mode = "browse"
        self._editor_mode_label = ""
        self._remove_cell_editor()
        self._render_all()
        self._scroll_active_row()

    def _commit_and_move_cell(self, delta: int) -> None:
        if self._mode != "cell" or self._busy or self._stage != "edit":
            return
        self._commit_cell()
        self._remove_cell_editor()
        self._editor_mode_label = ""
        self._select_relative_field(delta)
        field = self._active_field()
        if field is None or field.editor_kind in {"bool", "enum"}:
            self._mode = "browse"
            self._render_all()
            self._scroll_active_row()
            return
        self._mode = "cell"
        self._render_all()
        self._mount_cell_editor(field)

    def action_edit_or_confirm(self) -> None:
        if self._stage == "preview":
            self.action_confirm()
        else:
            self.action_edit_field()

    def action_edit_field(self) -> None:
        if self._busy or self._stage != "edit" or self._mode != "browse":
            return
        field = self._active_field()
        if field is None:
            return
        if field.editor_kind == "bool":
            self.action_toggle_value()
            return
        if field.editor_kind == "enum":
            self.action_cycle_value(1)
            return
        if field.reset:
            self._form = self._form.clear_change(field.name)
            field = self._form.field(field.name)
        self._mode = "cell"
        self._editor_mode_label = "INSERT"
        self._render_all()
        self._mount_cell_editor(field)

    def action_nav_down(self) -> None:
        if self._stage == "preview":
            self._scroll_preview(lines=1)
        else:
            self._move_field(1)

    def action_nav_up(self) -> None:
        if self._stage == "preview":
            self._scroll_preview(lines=-1)
        else:
            self._move_field(-1)

    def _move_field(self, delta: int) -> None:
        if self._mode != "browse" or self._busy:
            return
        self._select_relative_field(delta)
        self._error = None
        self._render_all()
        self._scroll_active_row()

    def _select_relative_field(self, delta: int) -> None:
        fields = self._form.fields
        if not fields:
            return
        names = [field.name for field in fields]
        index = names.index(self._active_name) if self._active_name in names else 0
        self._active_name = names[(index + delta) % len(names)]

    def action_top_or_first(self) -> None:
        if self._stage == "preview":
            self.action_preview_top()
            return
        if self._mode == "browse" and self._form.fields:
            self._active_name = self._form.fields[0].name
            self._render_all()
            self._scroll_active_row()

    def action_bottom_or_last(self) -> None:
        if self._stage == "preview":
            self.action_preview_bottom()
            return
        if self._mode == "browse" and self._form.fields:
            self._active_name = self._form.fields[-1].name
            self._render_all()
            self._scroll_active_row()

    def action_toggle_value(self) -> None:
        field = self._active_field()
        if (
            field is None
            or field.reset
            or self._busy
            or self._stage != "edit"
            or self._mode != "browse"
        ):
            return
        if field.editor_kind == "bool":
            self._form = self._form.set_value(field.name, not bool(field.draft_value))
        elif field.editor_kind == "enum":
            self._cycle_enum(field, 1)
        else:
            return
        self._error = None
        self._render_all()

    def action_cycle_value(self, direction: int) -> None:
        field = self._active_field()
        if (
            field is None
            or field.reset
            or field.editor_kind != "enum"
            or self._busy
            or self._stage != "edit"
            or self._mode != "browse"
        ):
            return
        self._cycle_enum(field, direction)
        self._error = None
        self._render_all()

    def _cycle_enum(self, field: SchemaObjectField, direction: int) -> None:
        values = field.enum_values
        if not values:
            return
        index = values.index(field.draft_value) if field.draft_value in values else -1
        self._form = self._form.set_value(
            field.name,
            values[(index + direction) % len(values)],
        )

    def action_select_scope(self, number: int) -> None:
        self._select_scope_index(number - 1)

    def action_toggle_reset(self) -> None:
        if self._busy or self._stage != "edit":
            return
        if self._mode == "cell":
            self._commit_cell()
            self._mode = "browse"
            self._editor_mode_label = ""
            self._remove_cell_editor()
        field = self._active_field()
        if field is None:
            return
        self._form = (
            self._form.clear_change(field.name)
            if field.reset
            else self._form.reset_field(field.name)
        )
        self._error = None
        self._render_all()

    def action_back(self) -> None:
        if self._busy:
            return
        if self._stage == "preview":
            self._mode = "browse"
            super().action_back()
            return
        if self._mode == "cell":
            self._leave_cell(commit=True)
            return
        super().action_back()

    def _field_index(self, name: str) -> int | None:
        return next(
            (
                index
                for index, field in enumerate(self._form.fields)
                if field.name == name
            ),
            None,
        )

    def _scroll_active_row(self) -> None:
        if not self.is_mounted or self._active_name is None:
            return
        index = self._field_index(self._active_name)
        if index is None:
            return
        try:
            self.query_one(f"#axe-editor-field-{index}").scroll_visible(animate=False)
        except Exception:
            pass

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if (
            self._stage != "edit"
            or self._mode != "cell"
            or self._busy
            or event.text_area is not self._cell_editor
        ):
            return
        name = getattr(event.text_area, "axe_field_name", None)
        if not isinstance(name, str):
            return
        self._form = self._form.set_text(name, event.text_area.text, live=True)
        self._error = None
        self.query_one("#axe-editor-run-status", Static).update(self._status_text())
        self._render_sheet()
        self._render_detail_dock()
        self._render_status_line()

    def on_single_line_vim_text_area_submitted(
        self,
        event: SingleLineVimTextArea.Submitted,
    ) -> None:
        if event.text_area is self._cell_editor and self._stage == "edit":
            self._leave_cell(commit=True)

    def on_click(self, event: events.Click) -> None:
        widget_id = getattr(event.widget, "id", None)
        if not isinstance(widget_id, str):
            return
        if widget_id.startswith("axe-editor-scope-"):
            try:
                index = int(widget_id.removeprefix("axe-editor-scope-"))
            except ValueError:
                return
            self._select_scope_index(index)
            event.stop()
            event.prevent_default()
            return
        value_click = widget_id.startswith(
            ("axe-editor-value-", "axe-editor-value-text-")
        )
        row_click = widget_id.startswith(
            (
                "axe-editor-field-",
                "axe-editor-name-",
                "axe-editor-badge-",
            )
        )
        if not value_click and not row_click:
            return
        try:
            index = int(widget_id.rsplit("-", 1)[1])
            field = self._form.fields[index]
        except (ValueError, IndexError):
            return
        if self._mode == "cell":
            self._leave_cell(commit=True)
        self._active_name = field.name
        self._render_all()
        self._scroll_active_row()
        if value_click:
            self.action_edit_field()
        event.stop()
        event.prevent_default()

    # -- shared transaction contract ----------------------------------

    def _writable_sources(self) -> list[AxeWritableScope]:
        return list(self._seed.writable_scopes)

    def _preview_scroll_widget(self) -> VerticalScroll:
        return self.query_one("#axe-editor-preview-scroll", VerticalScroll)

    def _build_transaction_mutation(self, target: str) -> AxeEntryMutationRequest:
        patch = self._form.patch()
        if not patch.is_valid:
            detail = "; ".join(
                f"{item.field}: {item.message}" for item in patch.diagnostics
            )
            raise ConfigTransactionInputError(detail)
        if not patch.operations:
            raise ConfigTransactionInputError("nothing changed")
        return AxeEntryMutationRequest(
            identity=self._seed.identity,
            target_scope=target,
            operations=patch.operations,
        )

    def _plan_transaction(
        self,
        request: ConfigTransactionRequest[AxeEntryMutationRequest],
    ) -> Any:
        return self._plan_entry(request.mutation)

    def _apply_transaction(self, plan: Any) -> ConfigTransactionApplyResult[Any]:
        outcome = self._apply_entry(plan)
        if isinstance(outcome, ConfigTransactionApplyResult):
            return outcome
        return ConfigTransactionApplyResult(outcome)

    def _accept_transaction_reload(self, value: Any) -> None:
        if not isinstance(value, AxeEntryEditorSeed):
            return
        # Preserve every user draft while refreshing scope/provenance metadata.
        old_form = self._form
        self._seed = value
        fresh = self._build_form(value, target=self._target)
        for old_field in old_form.fields:
            if not old_field.touched:
                continue
            try:
                fresh.field(old_field.name)
            except KeyError:
                continue
            fresh = fresh._replace(
                old_field.name,
                touched=True,
                reset=old_field.reset,
                draft_value=old_field.draft_value,
                draft_text=old_field.draft_text,
                parse_error=old_field.parse_error,
                parse_deferred=old_field.parse_deferred,
            )
        self._form = fresh

    def _transaction_scope_changed(self) -> None:
        by_scope = self._seed.raw_values_by_scope
        if by_scope is None:
            return
        values = by_scope.get(self._target or "", {})
        for field in self._form.fields:
            self._form = self._form._replace(
                field.name,
                has_target=field.name in values,
                target_value=values.get(field.name),
            )

    def _render_transaction_state(self) -> None:
        self._render_all()

    def _focus_transaction_draft(self) -> None:
        if self._mode == "cell":
            field = self._active_field()
            if field is not None:
                self._mount_cell_editor(field)
        else:
            self.set_focus(None)

    def action_confirm(self) -> None:
        if self._busy:
            return
        if self._stage == "edit" and self._mode == "cell":
            self._leave_cell(commit=True)
        if self._stage == "preview":
            self._restart_requested = self._seed.running
        super().action_confirm()

    def action_save_only(self) -> None:
        if self._busy or self._stage != "preview":
            return
        self._restart_requested = False
        self._start_apply()

    def _dismiss_transaction_result(self, value: Any) -> None:
        self.dismiss(
            AxeEntryEditorResult(
                identity=self._seed.identity,
                applied=value,
                restart_requested=self._restart_requested,
            )
        )


__all__ = [
    "AxeEntryEditorModal",
    "AxeEntryEditorResult",
    "AxeEntryEditorSeed",
    "AxeEntryIdentity",
    "AxeEntryKind",
    "AxeEntryMutationRequest",
    "AxeWritableScope",
    "axe_entry_schema",
]
