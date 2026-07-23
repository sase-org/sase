"""Textual composition and rendering for the AXE entry editor."""

from __future__ import annotations

import os
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
_HOME = os.path.expanduser("~")
_MODE_LABELS = {
    "insert": "INSERT",
    "normal": "NORMAL",
    "visual": "VISUAL",
    "visual_line": "V-LINE",
}


def _middle_ellipsize(value: str, width: int) -> str:
    """Fit *value* in *width* cells while preserving both identifying ends."""
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width == 1:
        return "…"
    left = (width - 1 + 1) // 2
    right = width - 1 - left
    return f"{value[:left]}…{value[-right:] if right else ''}"


def _end_ellipsize(value: str, width: int) -> str:
    """Fit single-line row content without allowing it to wrap."""
    value = " ".join(value.splitlines())
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width == 1:
        return "…"
    return f"{value[: width - 1]}…"


def _display_path(path: str, width: int) -> str:
    """Collapse the home prefix and middle-ellipsize a config path."""
    collapsed = path
    if _HOME and (path == _HOME or path.startswith(f"{_HOME}{os.sep}")):
        collapsed = f"~{path[len(_HOME) :]}"
    return _middle_ellipsize(collapsed, width)


class _AxeValueInput(SingleLineVimTextArea):
    """Single-line AXE value editor with calm, modal-specific vim chrome."""

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        mode = _MODE_LABELS.get(self._vim_mode, "")
        subtitle = mode
        if indicator:
            subtitle = f"{subtitle} · {indicator}" if subtitle else indicator
        self.border_title = "Value"
        self.border_subtitle = subtitle.replace("[", r"\[")


class _AxeValueTextArea(VimTextArea):
    """Multiline AXE value editor with a stable type title and mode subtitle."""

    _value_kind = "yaml"

    def set_value_kind(self, kind: str) -> None:
        self._value_kind = {
            "string_list": "list",
            "text": "text",
            "yaml": "yaml",
        }.get(kind, kind)
        self._update_vim_mode_display()

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        mode = _MODE_LABELS.get(self._vim_mode, "")
        subtitle = mode
        if indicator:
            subtitle = f"{subtitle} · {indicator}" if subtitle else indicator
        self.border_title = f"Value · {self._value_kind}"
        self.border_subtitle = subtitle.replace("[", r"\[")


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
                    with Vertical(id="axe-editor-scopes"):
                        with Horizontal(id="axe-editor-scope-row"):
                            yield Static(
                                "Scope",
                                id="axe-editor-scope-label",
                                markup=False,
                            )
                            for index, _scope in enumerate(self._seed.writable_scopes):
                                yield Static(
                                    "",
                                    id=f"axe-editor-scope-{index}",
                                    classes="axe-editor-scope-chip",
                                    markup=False,
                                )
                            yield Static(
                                "· ^T",
                                id="axe-editor-scope-hint",
                                markup=False,
                            )
                        yield Static(
                            "",
                            id="axe-editor-scope-path",
                            markup=False,
                        )
                    with VerticalScroll(id="axe-editor-properties"):
                        for group in ("basics", "advanced"):
                            yield Static(
                                group.upper(),
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
                            yield Static(
                                "",
                                id=f"axe-editor-{group}-add",
                                classes="axe-editor-add",
                                markup=False,
                            )
                with Vertical(id="axe-editor-value-pane"):
                    yield Static("", id="axe-editor-field-info", markup=False)
                    yield Static("", id="axe-editor-options", markup=False)
                    yield _AxeValueInput(
                        seed_text,
                        id="axe-editor-input",
                        placeholder="Enter a value…",
                    )
                    yield _AxeValueTextArea(
                        seed_text,
                        id="axe-editor-textarea",
                        language="yaml",
                        placeholder="Enter YAML or text…",
                        show_line_numbers=False,
                    )
                    yield Static("", id="axe-editor-validation", markup=False)
            with VerticalScroll(id="axe-editor-preview-scroll"):
                yield Static("", id="axe-editor-preview", markup=False)
            yield Static("", id="axe-editor-hints", markup=False)

    def on_mount(self: Any) -> None:
        self._set_narrow(self.app.size.width < _NARROW_BELOW)
        # Composed children are not mounted yet, so synchronous rendering here
        # would no-op behind _render_all's defensive is_mounted guard.
        self.call_after_refresh(self._initialize_editor)

    def _initialize_editor(self: Any) -> None:
        if not self.is_mounted:
            return
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
        self._render_scopes()
        for index, field in enumerate(self._form.fields):
            row = self.query_one(f"#axe-editor-field-{index}", Static)
            row.display = field.included
            row.set_class(field.name == self._active_name, "selected")
            row.update(
                self._field_row(
                    field,
                    width=max(24, row.content_size.width or 34),
                )
            )
        for group in ("basics", "advanced"):
            add = self.query_one(f"#axe-editor-{group}-add", Static)
            has_addable = bool(self._form.addable_fields(group))
            add.display = has_addable
            add.update("+ add property  a" if has_addable else "")
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
        input_editor = self.query_one("#axe-editor-input", _AxeValueInput)
        input_editor._update_vim_mode_display()
        text_editor = self.query_one("#axe-editor-textarea", _AxeValueTextArea)
        text_editor.set_value_kind(kind)

    def _title_text(self: Any) -> Text:
        identity = self._seed.identity
        text = Text()
        verb = "Add" if self._seed.new_entry else "Edit"
        text.append(f"{verb} AXE {identity.kind}", style="bold #F0C674")
        text.append(" · ", style="#B87333")
        text.append(identity.label, style="bold #E6B450")
        return text

    def _status_text(self: Any) -> Text:
        text = Text()
        if self._seed.running:
            text.append("● running", style="#87AF87")
        else:
            text.append("○ stopped", style="dim")
        if self._seed.status:
            text.append(f" · {self._seed.status}", style="dim")
        if self._seed.identity.generated_instance:
            text.append(
                f" · instance {self._seed.identity.generated_instance}", style="dim"
            )
        warning = self._seed.generated_warning
        if warning:
            text.append(f"\n! {warning}", style="bold #FFAF5F")
        return text

    def _render_scopes(self: Any) -> None:
        for index, scope in enumerate(self._seed.writable_scopes, start=1):
            active = scope.name == self._target
            chip = self.query_one(f"#axe-editor-scope-{index - 1}", Static)
            chip.update(f"{index} {scope.name}")
            chip.set_class(active, "active")
        target = next(
            (
                scope
                for scope in self._seed.writable_scopes
                if scope.name == self._target
            ),
            None,
        )
        path_widget = self.query_one("#axe-editor-scope-path", Static)
        if target is None or not target.path:
            path_widget.update(Text("No writable config path", style="dim"))
            return
        suffix = " · new" if not target.exists else ""
        width = max(12, path_widget.content_size.width or 34)
        path = _display_path(target.path, max(1, width - len(suffix)))
        text = Text(path, style="dim")
        if suffix:
            text.append(suffix, style="#FFAF5F")
        path_widget.update(text)

    def _field_row(self: Any, field: SchemaObjectField, *, width: int = 34) -> Text:
        selected = field.name == self._active_name
        marker = "> " if selected else "  "
        name = field.name
        if field.required:
            name += " *"
        if field.reset:
            badge = "inherit"
            badge_style = "#B87333"
        elif field.touched:
            badge = "edited"
            badge_style = "#87D787"
        elif field.source:
            badge = f"·{field.source}"
            badge_style = "dim"
        else:
            badge = "·local"
            badge_style = "dim"
        if field.reset and field.has_inherited:
            preview_value = field.inherited_value
        elif field.draft_text is not None and field.parse_error is not None:
            preview_value = field.draft_text
        else:
            preview_value = field.draft_value
        fixed_width = len(marker) + len(name) + len(badge) + 2
        preview = _end_ellipsize(
            format_value(preview_value),
            max(4, width - fixed_width),
        )
        spacing = " " * max(
            1,
            width - len(marker) - len(name) - len(preview) - len(badge) - 1,
        )
        text = Text(marker, style="#F0C674" if selected else "dim")
        name_text = name.removesuffix(" *")
        text.append(name_text, style="bold #F0C674" if selected else "")
        if field.required:
            text.append(" *", style="#F0C674")
        text.append(spacing)
        text.append(preview)
        text.append(" ")
        text.append(badge, style=badge_style)
        return text

    def _field_info(self: Any, field: SchemaObjectField | None) -> Text:
        if field is None:
            return Text("No editable properties.", style="dim")
        text = Text()
        text.append(field.name, style="bold #F0C674")
        text.append("  ")
        text.append(
            f" {field.editor_kind} ",
            style="bold #E6B450 on #3A2C1A",
        )
        if field.description:
            text.append(f"\n{field.description}")
        definitions: list[tuple[str, Any, str]] = []
        if field.has_effective:
            definitions.append(("Effective", field.effective_value, ""))
        if field.has_target:
            definitions.append(
                (f"Layer({self._target or 'target'})", field.target_value, "#D7A85B")
            )
        if field.has_inherited and (field.reset or not field.has_target):
            definitions.append(("Inherits", field.inherited_value, "#D7A85B"))
        label_width = max(
            (len(label) for label, _value, _style in definitions), default=0
        )
        for label, value, style in definitions:
            text.append(f"\n{label:<{label_width}}  ", style="dim")
            text.append(format_value(value), style=style)
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
        text = Text("Value  ", style="bold #B87333")
        for index, value in enumerate(values, start=1):
            active = value == field.draft_value
            if index > 1:
                text.append("  ")
            text.append(
                f" {index} {format_value(value)} ",
                style=("bold #100F0F on #F0C674" if active else "dim"),
            )
        return text

    def _validation_text(self: Any, field: SchemaObjectField | None) -> Text:
        if self._error:
            return Text(f"! {self._error}", style="bold #FF8787")
        if field is not None and field.parse_error:
            return Text(f"! {field.parse_error}", style="bold #FF8787")
        if field is not None and field.parse_deferred:
            return Text("large YAML buffer; preview validates it", style="dim")
        if self._status:
            return Text(self._status, style="dim")
        return Text("")

    def _hints(self: Any) -> str:
        if self._stage == "preview":
            if self._busy:
                return "Working…"
            primary = "save & restart" if self._seed.running else "save"
            if self.has_class("-narrow"):
                return f"↑↓ scroll · ^D/^U page · ⏎ {primary} · esc back"
            save_only = " · ^O save only" if self._seed.running else ""
            return f"↑↓ scroll · ^D/^U page · ⏎ {primary}{save_only} · esc back"
        if self.has_class("-narrow"):
            return "↑↓  a:add  spc:toggle  ^R:inherit  ^T:scope  ⏎:preview  esc"
        return (
            "↑↓ field · a add · space toggle · ^R inherit · ^T scope · ⏎ preview · esc"
        )

    @staticmethod
    def _field_editor_text(field: SchemaObjectField | None) -> str:
        if field is None:
            return ""
        if field.draft_text is not None:
            return field.draft_text
        return format_value_for_editor(field.editor_kind, field.draft_value)
