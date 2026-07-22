"""Textual composition and rendering for the AXE entry editor."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Label, Static

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from .config_edit_helpers import format_value, format_value_for_editor
from .config_transaction_preview import (
    coerce_transaction_preview,
    render_transaction_preview,
)
from .schema_object_form import SchemaObjectField


_NARROW_BELOW = 90


class AxeEntryEditorRenderingMixin:
    """Layout and render methods shared by the AXE editor modal."""

    def compose(self: Any) -> ComposeResult:
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

    def on_mount(self: Any) -> None:
        self._set_narrow(self.app.size.width < _NARROW_BELOW)
        self._render_all(force_editor=True)
        self._focus_editor()

    def on_resize(self: Any, event: events.Resize) -> None:
        self._set_narrow(event.size.width < _NARROW_BELOW)

    def _set_narrow(self: Any, narrow: bool) -> None:
        self.set_class(narrow, "-narrow")

    def _render_all(self: Any, *, force_editor: bool = False) -> None:
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

    def _sync_visibility(self: Any, field: SchemaObjectField | None) -> None:
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

    def _title_text(self: Any) -> Text:
        identity = self._seed.identity
        text = Text()
        verb = "Add" if self._seed.new_entry else "Edit"
        text.append(f"{verb} AXE {identity.kind}  ", style="bold #D7A85B")
        text.append(identity.label, style="bold #F0C674")
        return text

    def _status_text(self: Any) -> Text:
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

    def _scope_text(self: Any) -> Text:
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

    def _field_row(self: Any, field: SchemaObjectField) -> Text:
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

    def _field_info(self: Any, field: SchemaObjectField | None) -> Text:
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

    def _option_text(self: Any, field: SchemaObjectField | None) -> Text:
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

    def _validation_text(self: Any, field: SchemaObjectField | None) -> Text:
        if self._error:
            return Text(f"✗ {self._error}", style="#FF8787")
        if field is not None and field.parse_error:
            return Text(f"✗ {field.parse_error}", style="#FF8787")
        if field is not None and field.parse_deferred:
            return Text("large YAML buffer; preview validates it", style="dim")
        if self._status:
            return Text(self._status, style="dim")
        return Text("")

    def _hints(self: Any) -> str:
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

    @staticmethod
    def _field_editor_text(field: SchemaObjectField | None) -> str:
        if field is None:
            return ""
        if field.draft_text is not None:
            return field.draft_text
        return format_value_for_editor(field.editor_kind, field.draft_value)
