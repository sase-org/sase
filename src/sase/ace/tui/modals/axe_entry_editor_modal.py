"""Reusable AXE lumberjack/chop schema editor surface.

This modal intentionally has no AXE-tab or daemon dependencies.  Integrations
provide immutable seed data plus plan/apply callbacks; the modal returns the
successful write value and whether the caller should reconcile a running AXE.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any, Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from .config_edit_helpers import format_value, format_value_for_editor
from .config_transaction import (
    ConfigTransactionApplyResult,
    ConfigTransactionControllerMixin,
    ConfigTransactionInputError,
    ConfigTransactionMetadata,
    ConfigTransactionRequest,
)
from .config_transaction_preview import (
    ConfigTransactionPreview,
    coerce_transaction_preview,
    render_transaction_preview,
)
from .property_picker_modal import PropertyPickerItem, PropertyPickerModal
from .schema_object_form import (
    SchemaFieldOperation,
    SchemaObjectField,
    SchemaObjectForm,
    resolve_schema_node,
)


AxeEntryKind = Literal["lumberjack", "chop"]
_BASICS_BY_KIND: dict[AxeEntryKind, tuple[str, ...]] = {
    "lumberjack": ("interval", "chop_timeout"),
    "chop": ("script", "description", "enabled", "run_every", "timeout"),
}
_ADVANCED_BY_KIND: dict[AxeEntryKind, tuple[str, ...]] = {
    "lumberjack": ("env",),
    "chop": ("env", "inhibit_if", "trigger", "once_per", "for_each", "vars"),
}
_INITIAL_BY_KIND: dict[AxeEntryKind, tuple[str, ...]] = {
    "lumberjack": ("interval",),
    "chop": ("script", "description", "enabled"),
}
_NARROW_BELOW = 90


@dataclass(frozen=True)
class AxeEntryIdentity:
    """Stable immutable identity shown by and returned from the editor."""

    kind: AxeEntryKind
    lumberjack: str
    chop: str | None = None
    generated_instance: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "chop" and not self.chop:
            raise ValueError("chop identity requires a chop name")

    @property
    def label(self) -> str:
        if self.kind == "lumberjack":
            return self.lumberjack
        return f"{self.lumberjack} / {self.chop}"


@dataclass(frozen=True)
class AxeWritableScope:
    """One writable AXE config layer in the modal's scope rail."""

    name: str
    path: str | None = None
    kind: str = "user"
    exists: bool = True
    list_strategy: str = "concatenate"


@dataclass(frozen=True)
class AxeEntryEditorSeed:
    """Immutable data needed to edit one AXE entry."""

    identity: AxeEntryIdentity
    schema: Mapping[str, Any]
    writable_scopes: tuple[AxeWritableScope, ...]
    effective_values: Mapping[str, Any] = dataclass_field(default_factory=dict)
    raw_values: Mapping[str, Any] = dataclass_field(default_factory=dict)
    target_values: Mapping[str, Any] | None = None
    provenance: Mapping[str, str | Sequence[str]] = dataclass_field(
        default_factory=dict
    )
    initial_target: str | None = None
    inherited_values: Mapping[str, Any] | None = None
    raw_values_by_scope: Mapping[str, Mapping[str, Any]] | None = None
    key_prefix: tuple[str, ...] = ()
    generated_warning: str | None = None
    running: bool = False
    status: str | None = None


@dataclass(frozen=True)
class AxeEntryMutationRequest:
    """Sparse exact-segment request passed to the injected planner."""

    identity: AxeEntryIdentity
    target_scope: str
    operations: tuple[SchemaFieldOperation, ...]


@dataclass(frozen=True)
class AxeEntryEditorResult:
    """Successful write plus the caller-owned runtime consequence."""

    identity: AxeEntryIdentity
    applied: Any
    restart_requested: bool

    @property
    def save_only(self) -> bool:
        return not self.restart_requested


class AxeEntryEditorModal(
    ConfigTransactionControllerMixin, ModalScreen[AxeEntryEditorResult | None]
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
                title=f"Edit AXE {seed.identity.kind}",
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
        object_schema = axe_entry_schema(seed.schema, seed.identity.kind)
        basics = _BASICS_BY_KIND[seed.identity.kind]
        advanced = _ADVANCED_BY_KIND[seed.identity.kind]
        target_values = seed.target_values
        if (
            seed.raw_values_by_scope is not None
            and target is not None
            and target in seed.raw_values_by_scope
        ):
            target_values = seed.raw_values_by_scope[target]
        form = SchemaObjectForm.build(
            schema_root=seed.schema,
            object_schema=object_schema,
            effective_values=seed.effective_values,
            target_values=(
                target_values if target_values is not None else seed.raw_values
            ),
            inherited_values=seed.inherited_values,
            provenance=seed.provenance,
            key_prefix=seed.key_prefix,
            basics=basics,
            advanced=advanced,
            initially_included=_INITIAL_BY_KIND[seed.identity.kind],
        )
        allowed = {*basics, *advanced}
        return replace(form, fields=tuple(f for f in form.fields if f.name in allowed))

    # -- Textual composition/rendering --------------------------------

    def compose(self) -> ComposeResult:
        active = self._active_field()
        seed_text = self._field_editor_text(active) if active is not None else ""
        with Container(id="axe-editor-container"):
            yield Label("", id="axe-editor-title")
            yield Static("", id="axe-editor-status", markup=False)
            with Horizontal(id="axe-editor-body"):
                with Vertical(id="axe-editor-navigation"):
                    yield Static("", id="axe-editor-scopes", markup=False)
                    with VerticalScroll(id="axe-editor-properties"):
                        for group in ("basics", "advanced"):
                            yield Static(
                                group.title(),
                                id=f"axe-editor-{group}-header",
                                classes="axe-editor-group-header",
                            )
                            for index, field in enumerate(self._form.fields):
                                if field.group == group:
                                    yield Static(
                                        "",
                                        id=f"axe-editor-field-{index}",
                                        classes=(
                                            f"axe-editor-field axe-editor-{field.group}"
                                        ),
                                        markup=False,
                                    )
                    yield Static("", id="axe-editor-add-guidance", markup=False)
                with Vertical(id="axe-editor-value-pane"):
                    yield Static("", id="axe-editor-field-info", markup=False)
                    yield Static("", id="axe-editor-options", markup=False)
                    yield SingleLineVimTextArea(seed_text, id="axe-editor-input")
                    yield VimTextArea(
                        seed_text,
                        id="axe-editor-textarea",
                        language="yaml",
                        show_line_numbers=False,
                    )
                    yield Static("", id="axe-editor-validation", markup=False)
            with VerticalScroll(id="axe-editor-preview-scroll"):
                yield Static("", id="axe-editor-preview", markup=False)
            yield Static("", id="axe-editor-hints", markup=False)

    def on_mount(self) -> None:
        self._set_narrow(self.app.size.width < _NARROW_BELOW)
        self._render_all(force_editor=True)
        self._focus_editor()

    def on_resize(self, event: events.Resize) -> None:
        self._set_narrow(event.size.width < _NARROW_BELOW)

    def _set_narrow(self, narrow: bool) -> None:
        self.set_class(narrow, "-narrow")

    def _render_all(self, *, force_editor: bool = False) -> None:
        if not self.is_mounted:
            return
        self.query_one("#axe-editor-title", Static).update(self._title_text())
        self.query_one("#axe-editor-status", Static).update(self._status_text())
        self.query_one("#axe-editor-scopes", Static).update(self._scope_text())
        for index, field in enumerate(self._form.fields):
            row = self.query_one(f"#axe-editor-field-{index}", Static)
            row.display = field.included
            row.update(self._field_row(field))
            row.set_class(field.name == self._active_name, "selected")
        addable = self._form.addable_fields()
        guidance = "a  add optional/advanced property" if addable else ""
        self.query_one("#axe-editor-add-guidance", Static).update(guidance)
        active = self._active_field()
        self.query_one("#axe-editor-field-info", Static).update(
            self._field_info(active)
        )
        self.query_one("#axe-editor-options", Static).update(self._option_text(active))
        self.query_one("#axe-editor-validation", Static).update(
            self._validation_text(active)
        )
        preview = self.query_one("#axe-editor-preview", Static)
        if self._stage == "preview":
            if self._busy and self._plan is None:
                preview.update(Text("Planning…", style="#888888"))
            elif self._plan is not None:
                preview.update(
                    render_transaction_preview(coerce_transaction_preview(self._plan))
                )
            else:
                preview.update("")
        else:
            preview.update("")
        self.query_one("#axe-editor-hints", Static).update(self._hints())
        self._sync_visibility(active)
        if active is not None and (
            force_editor or self._loaded_editor_name != active.name
        ):
            self._load_editor(active)

    def _sync_visibility(self, field: SchemaObjectField | None) -> None:
        edit = self._stage == "edit"
        kind = field.editor_kind if field is not None else "yaml"
        reset = bool(field and field.reset)
        self.query_one("#axe-editor-body").display = edit
        self.query_one("#axe-editor-preview-scroll").display = not edit
        self.query_one("#axe-editor-options").display = (
            edit and not reset and kind in {"bool", "enum"}
        )
        self.query_one("#axe-editor-input").display = (
            edit and not reset and kind in {"int", "number", "string"}
        )
        self.query_one("#axe-editor-textarea").display = (
            edit and not reset and kind in {"text", "string_list", "yaml"}
        )

    def _title_text(self) -> Text:
        identity = self._seed.identity
        text = Text()
        text.append(f"Edit AXE {identity.kind}  ", style="bold #D7A85B")
        text.append(identity.label, style="bold #F0C674")
        return text

    def _status_text(self) -> Text:
        text = Text()
        state = "running" if self._seed.running else "stopped"
        text.append(f"AXE {state}", style="#87AF87" if self._seed.running else "dim")
        if self._seed.status:
            text.append(f" · {self._seed.status}", style="dim")
        if self._seed.identity.generated_instance:
            text.append(
                f" · instance {self._seed.identity.generated_instance}", style="dim"
            )
        warning = self._seed.generated_warning
        if warning:
            text.append(f"\n⚠ {warning}", style="#FFAF5F")
        return text

    def _scope_text(self) -> Text:
        text = Text("Scope", style="bold #B87333")
        text.append("  [ctrl+t cycles]\n", style="dim")
        for index, scope in enumerate(self._seed.writable_scopes, start=1):
            active = scope.name == self._target
            text.append("> " if active else "  ", style="#F0C674" if active else "dim")
            text.append(f"{index}. {scope.name}", style="bold" if active else "")
            text.append(f"  {scope.kind}", style="dim")
            if not scope.exists:
                text.append(" · new", style="#FFAF5F")
            text.append("\n")
        target = next(
            (
                scope
                for scope in self._seed.writable_scopes
                if scope.name == self._target
            ),
            None,
        )
        if target is not None and target.path:
            text.append(target.path, style="dim")
        return text

    def _field_row(self, field: SchemaObjectField) -> Text:
        selected = field.name == self._active_name
        text = Text("▸ " if selected else "  ", style="#F0C674" if selected else "dim")
        text.append(field.name, style="bold #F0C674" if selected else "")
        if field.required:
            text.append(" *", style="#FFAF5F")
        if field.reset:
            text.append("  [inherit]", style="#B87333")
        elif field.touched:
            text.append("  [edited]", style="#87D787")
        if field.source:
            text.append(f"  [{field.source}]", style="dim #B87333")
        return text

    def _field_info(self, field: SchemaObjectField | None) -> Text:
        if field is None:
            return Text("No editable properties.", style="dim")
        text = Text()
        text.append(field.name, style="bold #F0C674")
        text.append(f"  {field.editor_kind}", style="dim")
        if field.description:
            text.append(f"\n{field.description}", style="dim")
        if field.has_effective:
            text.append("\nEffective: ", style="dim")
            text.append(format_value(field.effective_value))
        if field.has_target:
            text.append("\nTarget layer: ", style="dim")
            text.append(format_value(field.target_value), style="#D7A85B")
        if field.reset:
            text.append(
                "\nInherit/reset removes this target-layer field.", style="#B87333"
            )
        return text

    def _option_text(self, field: SchemaObjectField | None) -> Text:
        if field is None:
            return Text("")
        if field.editor_kind == "bool":
            values: tuple[Any, ...] = (True, False)
        elif field.editor_kind == "enum":
            values = field.enum_values
        else:
            return Text("")
        text = Text("Value\n", style="dim")
        for index, value in enumerate(values, start=1):
            active = value == field.draft_value
            text.append("> " if active else "  ", style="#F0C674" if active else "dim")
            text.append(
                f"{index}. {format_value(value)}", style="bold" if active else ""
            )
            text.append("\n")
        return text

    def _validation_text(self, field: SchemaObjectField | None) -> Text:
        if self._error:
            return Text(f"✗ {self._error}", style="#FF8787")
        if field is not None and field.parse_error:
            return Text(f"✗ {field.parse_error}", style="#FF8787")
        if field is not None and field.parse_deferred:
            return Text("large YAML buffer; preview validates it", style="dim")
        if self._status:
            return Text(self._status, style="dim")
        return Text("")

    def _hints(self) -> str:
        if self._stage == "preview":
            if self._busy:
                return "working…"
            primary = "save & restart AXE" if self._seed.running else "save"
            save_only = "  ctrl+o: save only" if self._seed.running else ""
            return (
                "j/k: scroll  ctrl+d/u: page  g/G: top/bottom  "
                f"enter/ctrl+s: {primary}{save_only}  esc: back"
            )
        return (
            "j/k: field  a: add property  space: bool/enum  ctrl+r: inherit  "
            "ctrl+t: scope  ctrl+s: preview  esc: cancel"
        )

    # -- editor interaction --------------------------------------------

    def _active_field(self) -> SchemaObjectField | None:
        if self._active_name is None:
            return None
        try:
            return self._form.field(self._active_name)
        except KeyError:
            return None

    @staticmethod
    def _field_editor_text(field: SchemaObjectField | None) -> str:
        if field is None:
            return ""
        if field.draft_text is not None:
            return field.draft_text
        return format_value_for_editor(field.editor_kind, field.draft_value)

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
        addable = self._form.addable_fields()
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
            for field in addable
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
        if widget_id == "axe-editor-scopes":
            widget = event.widget
            if widget is None:
                return
            offset = event.get_content_offset(widget)
            y = offset.y if offset is not None else int(event.y)
            self._select_scope_index(y - 1)
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


def axe_entry_schema(
    schema_root: Mapping[str, Any], kind: AxeEntryKind
) -> Mapping[str, Any]:
    """Resolve the bundled lumberjack or chop object schema."""
    # Tests and embedding callers may pass the object schema directly.
    properties = schema_root.get("properties")
    if isinstance(properties, Mapping):
        expected = "interval" if kind == "lumberjack" else "script"
        if expected in properties:
            return schema_root
    if kind == "chop":
        resolved = resolve_schema_node(schema_root, {"$ref": "#/definitions/axeChop"})
    else:
        node: Any = schema_root
        for segment in ("axe", "lumberjacks"):
            node = resolve_schema_node(schema_root, node)
            node_properties = (
                node.get("properties", {}) if isinstance(node, Mapping) else {}
            )
            if (
                not isinstance(node_properties, Mapping)
                or segment not in node_properties
            ):
                raise ValueError("schema does not contain AXE lumberjack definitions")
            node = node_properties[segment]
        node = resolve_schema_node(schema_root, node)
        resolved = (
            resolve_schema_node(schema_root, node.get("additionalProperties"))
            if isinstance(node, Mapping)
            else None
        )
    if not isinstance(resolved, Mapping):
        raise ValueError(f"schema does not contain an AXE {kind} definition")
    return resolved


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
