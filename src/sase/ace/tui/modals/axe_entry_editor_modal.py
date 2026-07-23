"""Reusable AXE lumberjack/chop schema editor surface.

This modal intentionally has no AXE-tab or daemon dependencies. Integrations
provide immutable seed data plus plan/apply callbacks; the modal returns the
successful write value and whether the caller should reconcile a running AXE.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from textual import events
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from .axe_entry_editor_rendering import AxeEntryEditorRenderingMixin
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
from .config_edit_helpers import format_value
from .config_transaction import (
    ConfigTransactionApplyResult,
    ConfigTransactionControllerMixin,
    ConfigTransactionInputError,
    ConfigTransactionMetadata,
    ConfigTransactionRequest,
)
from .property_picker_modal import PropertyPickerItem, PropertyPickerModal
from .schema_object_form import SchemaObjectField, SchemaObjectForm


class AxeEntryEditorModal(
    AxeEntryEditorRenderingMixin,
    ConfigTransactionControllerMixin,
    ModalScreen[AxeEntryEditorResult | None],
):
    """Edit a lumberjack or base chop through a sparse schema form."""

    AUTO_FOCUS = None
    BINDINGS = [
        ("escape", "back", "Back/Cancel"),
        ("ctrl+s", "confirm", "Preview/Save"),
        ("enter", "confirm", "Preview/Save"),
        ("ctrl+o", "save_only", "Save only"),
        ("j", "nav_down", "Down"),
        ("k", "nav_up", "Up"),
        ("down", "nav_down", "Down"),
        ("up", "nav_up", "Up"),
        ("ctrl+d", "preview_page_down", "Page Down"),
        ("ctrl+u", "preview_page_up", "Page Up"),
        ("g", "preview_top", "Top"),
        ("G", "preview_bottom", "Bottom"),
        ("space", "toggle_value", "Toggle"),
        ("a", "add_property", "Add property"),
        ("ctrl+t", "cycle_scope", "Scope"),
        ("ctrl+r", "toggle_reset", "Inherit/reset"),
        ("ctrl+l", "reload_transaction", "Reload"),
        Binding("1", "pick_option(1)", "Pick 1", show=False),
        Binding("2", "pick_option(2)", "Pick 2", show=False),
        Binding("3", "pick_option(3)", "Pick 3", show=False),
        Binding("4", "pick_option(4)", "Pick 4", show=False),
        Binding("5", "pick_option(5)", "Pick 5", show=False),
        Binding("6", "pick_option(6)", "Pick 6", show=False),
        Binding("7", "pick_option(7)", "Pick 7", show=False),
        Binding("8", "pick_option(8)", "Pick 8", show=False),
        Binding("9", "pick_option(9)", "Pick 9", show=False),
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
        self._target = self._initial_target(seed)
        self._busy = False
        self._error: str | None = None
        self._status: str | None = None
        self._plan: Any = None
        self._restart_requested = False
        self._form = self._build_form(seed, target=self._target)
        visible = self._form.visible_fields()
        self._active_name = visible[0].name if visible else None
        self._ignore_editor_values: dict[str, str] = {}
        self._loaded_editor_name: str | None = None
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

    # -- editor interaction --------------------------------------------

    def _active_field(self) -> SchemaObjectField | None:
        if self._active_name is None:
            return None
        try:
            return self._form.field(self._active_name)
        except KeyError:
            return None

    def _load_editor(self, field: SchemaObjectField) -> None:
        text = self._field_editor_text(field)
        if field.editor_kind in {"int", "number", "string"}:
            editor: VimTextArea = self.query_one(
                "#axe-editor-input", SingleLineVimTextArea
            )
            self._ignore_editor_values["axe-editor-input"] = text
            editor.text = text
        elif field.editor_kind in {"text", "string_list", "yaml"}:
            editor = self.query_one("#axe-editor-textarea", VimTextArea)
            self._ignore_editor_values["axe-editor-textarea"] = text
            editor.text = text
        self._loaded_editor_name = field.name

    def _focus_editor(self) -> None:
        if self._stage != "edit":
            self.set_focus(None)
            return
        field = self._active_field()
        if field is None or field.reset:
            self.set_focus(None)
            return
        try:
            if field.editor_kind in {"int", "number", "string"}:
                editor: VimTextArea = self.query_one(
                    "#axe-editor-input", SingleLineVimTextArea
                )
                editor.focus()
                editor.select_all()
            elif field.editor_kind in {"text", "string_list", "yaml"}:
                editor = self.query_one("#axe-editor-textarea", VimTextArea)
                editor.focus()
            else:
                self.set_focus(None)
                return
            editor._update_vim_mode_display()
        except Exception:
            self.set_focus(None)

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
        fields = self._form.visible_fields()
        if not fields or self._busy:
            return
        names = [field.name for field in fields]
        index = names.index(self._active_name) if self._active_name in names else 0
        self._active_name = names[(index + delta) % len(names)]
        self._loaded_editor_name = None
        self._error = None
        self._render_all()
        self._focus_editor()

    def action_toggle_value(self) -> None:
        field = self._active_field()
        if field is None or field.reset or self._busy or self._stage != "edit":
            return
        if field.editor_kind == "bool":
            self._form = self._form.set_value(field.name, not bool(field.draft_value))
        elif field.editor_kind == "enum" and field.enum_values:
            values = field.enum_values
            index = (
                values.index(field.draft_value) if field.draft_value in values else -1
            )
            self._form = self._form.set_value(
                field.name, values[(index + 1) % len(values)]
            )
        else:
            return
        self._render_all()

    def action_pick_option(self, number: int) -> None:
        field = self._active_field()
        if field is None or field.reset or self._stage != "edit":
            return
        values: Sequence[Any]
        if field.editor_kind == "bool":
            values = (True, False)
        elif field.editor_kind == "enum":
            values = field.enum_values
        else:
            return
        if 0 < number <= len(values):
            self._form = self._form.set_value(field.name, values[number - 1])
            self._render_all()

    def action_toggle_reset(self) -> None:
        field = self._active_field()
        if field is None or self._busy or self._stage != "edit":
            return
        self._form = (
            self._form.clear_change(field.name)
            if field.reset
            else self._form.reset_field(field.name)
        )
        self._error = None
        self._loaded_editor_name = None
        self._render_all()
        self._focus_editor()

    def action_add_property(self) -> None:
        if self._busy or self._stage != "edit":
            return
        properties = [
            PropertyPickerItem(
                name=field.name,
                description=field.description,
                kind="structured" if field.compound else field.editor_kind,
                allowed_values=(
                    ", ".join(format_value(value) for value in field.enum_values)
                    if field.enum_values
                    else None
                ),
            )
            for field in self._form.addable_fields()
        ]

        def picked(name: str | None) -> None:
            if not name or not self.is_mounted or not self.query("#axe-editor-title"):
                return
            self._form = self._form.include(name)
            self._active_name = name
            self._loaded_editor_name = None
            self._render_all()
            self._focus_editor()

        self.app.push_screen(
            PropertyPickerModal(
                properties,
                title=f"Add {self._seed.identity.kind} property",
                guidance="Compound and ambiguous properties open as raw YAML.",
                empty_message="All schema properties are already shown.",
            ),
            picked,
        )

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self._stage != "edit" or self._busy:
            return
        editor_id = event.text_area.id or ""
        if editor_id not in {"axe-editor-input", "axe-editor-textarea"}:
            return
        ignored = self._ignore_editor_values.get(editor_id)
        if ignored is not None and event.text_area.text == ignored:
            self._ignore_editor_values.pop(editor_id, None)
            return
        field = self._active_field()
        if field is None:
            return
        self._form = self._form.set_text(field.name, event.text_area.text, live=True)
        self._error = None
        self._render_all()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        if event.text_area.id == "axe-editor-input" and self._stage == "edit":
            self._start_plan()

    def on_click(self, event: events.Click) -> None:
        widget_id = getattr(event.widget, "id", None)
        if isinstance(widget_id, str) and widget_id.startswith("axe-editor-scope-"):
            try:
                index = int(widget_id.removeprefix("axe-editor-scope-"))
            except ValueError:
                return
            self._select_scope_index(index)
            event.stop()
            event.prevent_default()
            return
        if widget_id in {"axe-editor-basics-add", "axe-editor-advanced-add"}:
            self.action_add_property()
            event.stop()
            event.prevent_default()
            return
        if isinstance(widget_id, str) and widget_id.startswith("axe-editor-field-"):
            try:
                index = int(widget_id.removeprefix("axe-editor-field-"))
                field = self._form.fields[index]
            except (ValueError, IndexError):
                return
            if field.included:
                self._active_name = field.name
                self._loaded_editor_name = None
                self._render_all()
                self._focus_editor()
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
        self, request: ConfigTransactionRequest[AxeEntryMutationRequest]
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
                included=True,
                touched=True,
                reset=old_field.reset,
                draft_value=old_field.draft_value,
                draft_text=old_field.draft_text,
                parse_error=old_field.parse_error,
                parse_deferred=old_field.parse_deferred,
            )
        self._form = fresh
        self._loaded_editor_name = None

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
        self._focus_editor()

    def action_confirm(self) -> None:
        if self._busy:
            return
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
