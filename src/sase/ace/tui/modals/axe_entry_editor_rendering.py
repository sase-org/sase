"""Textual composition and rendering for the AXE entry property sheet."""

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

from .axe_entry_sheet import (
    AxeEntrySheetRow,
    build_sheet_rows,
    detail_dock_lines,
    hint_text,
    sheet_column_widths,
    status_line_text,
)
from .config_edit_helpers import format_value_for_editor
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
_BADGE_COLORS = {
    "source": "dim",
    "unset": "dim",
    "edited": "bold #87D787",
    "inherit": "bold #D7A85B",
    "invalid": "bold #FF8787",
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


def _route_cell_tab(editor: Any, event: events.Key) -> bool:
    """Route Tab past a focused TextArea to the owning sheet."""
    if event.key not in {"tab", "shift+tab", "backtab"}:
        return False
    event.stop()
    event.prevent_default()
    delta = -1 if event.key in {"shift+tab", "backtab"} else 1
    try:
        screen = editor.screen
        callback = screen._commit_and_move_cell
        screen.call_after_refresh(lambda: callback(delta))
    except Exception:
        pass
    return True


def _route_vim_mode(editor: Any, indicator: str = "") -> None:
    """Send a focused editor's vim mode to the fixed detail dock."""
    mode = _MODE_LABELS.get(editor._vim_mode, "")
    if indicator:
        mode = f"{mode} · {indicator}" if mode else indicator
    try:
        callback = editor.screen._set_editor_mode_label
        callback(mode)
    except Exception:
        pass


def _route_cell_mounted(editor: Any) -> None:
    """Notify the sheet only after Textual has actually mounted the editor."""
    try:
        editor.screen._cell_editor_mounted(editor)
    except Exception:
        pass


class _AxeValueVimHostMixin:
    """Shared vim host policy for AXE value-cell editors."""

    def _host_claims_unhandled_vim_key(self, event: events.Key) -> bool:
        """Let NORMAL-mode ``q`` reach the sheet's ``quit_editor`` binding."""
        return event.character == "q"


class AxeValueInput(_AxeValueVimHostMixin, SingleLineVimTextArea):
    """Borderless single-line editor mounted in the active value cell."""

    def __init__(self, text: str, *, field_name: str, generation: int) -> None:
        self.axe_field_name = field_name
        super().__init__(
            text,
            id=f"axe-editor-cell-input-{generation}",
            classes="axe-editor-cell-editor",
            placeholder="Enter a value…",
        )

    async def _on_key(self, event: events.Key) -> None:
        # Textual continues walking the _on_key MRO for unconsumed events.
        _route_cell_tab(self, event)

    def on_mount(self) -> None:
        super().on_mount()
        _route_cell_mounted(self)

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        _route_vim_mode(self, indicator)


class AxeValueTextArea(_AxeValueVimHostMixin, VimTextArea):
    """Borderless multi-line editor mounted in the active value cell."""

    def __init__(
        self,
        text: str,
        *,
        field_name: str,
        value_kind: str,
        generation: int,
    ) -> None:
        self.axe_field_name = field_name
        self._value_kind = value_kind
        super().__init__(
            text,
            id=f"axe-editor-cell-textarea-{generation}",
            classes="axe-editor-cell-editor axe-editor-cell-textarea",
            language="yaml",
            placeholder="Enter YAML or text…",
            show_line_numbers=False,
        )

    async def _on_key(self, event: events.Key) -> None:
        # Multi-line Enter remains owned by VimTextArea; only Tab is special.
        _route_cell_tab(self, event)

    def on_mount(self) -> None:
        super().on_mount()
        _route_cell_mounted(self)

    def _update_vim_mode_display(self, indicator: str = "") -> None:
        _route_vim_mode(self, indicator)


class AxeEntryEditorRenderingMixin:
    """Layout and render methods shared by the AXE editor modal."""

    def compose(self: Any) -> ComposeResult:
        with Container(id="axe-editor-container"):
            yield Label("", id="axe-editor-title")
            with Horizontal(id="axe-editor-meta"):
                yield Static("", id="axe-editor-run-status", markup=False)
                with Horizontal(id="axe-editor-scope-row"):
                    yield Static("Scope", id="axe-editor-scope-label", markup=False)
                    for index, _scope in enumerate(self._seed.writable_scopes):
                        yield Static(
                            "",
                            id=f"axe-editor-scope-{index}",
                            classes="axe-editor-scope-chip",
                            markup=False,
                        )
            with Horizontal(id="axe-editor-context"):
                yield Static("", id="axe-editor-warning", markup=False)
                yield Static("", id="axe-editor-scope-path", markup=False)
            with VerticalScroll(id="axe-editor-sheet"):
                for group in ("basics", "advanced"):
                    yield Static(
                        group.upper(),
                        id=f"axe-editor-{group}-header",
                        classes="axe-editor-group-header",
                        markup=False,
                    )
                    for index, field in enumerate(self._form.fields):
                        if field.group != group:
                            continue
                        with Horizontal(
                            id=f"axe-editor-field-{index}",
                            classes=f"axe-editor-field axe-editor-{field.group}",
                        ):
                            yield Static(
                                "",
                                id=f"axe-editor-name-{index}",
                                classes="axe-editor-field-name",
                                markup=False,
                            )
                            with Container(
                                id=f"axe-editor-value-{index}",
                                classes="axe-editor-field-value-cell",
                            ):
                                yield Static(
                                    "",
                                    id=f"axe-editor-value-text-{index}",
                                    classes="axe-editor-field-value",
                                    markup=False,
                                )
                            yield Static(
                                "",
                                id=f"axe-editor-badge-{index}",
                                classes="axe-editor-field-badge",
                                markup=False,
                            )
            with Vertical(id="axe-editor-dock"):
                yield Static("", id="axe-editor-dock-header", markup=False)
                yield Static("", id="axe-editor-dock-description", markup=False)
                yield Static("", id="axe-editor-dock-values", markup=False)
            yield Static("", id="axe-editor-status", markup=False)
            with VerticalScroll(id="axe-editor-preview-scroll"):
                yield Static("", id="axe-editor-preview", markup=False)
            yield Static("", id="axe-editor-hints", markup=False)

    def on_mount(self: Any) -> None:
        self._set_narrow(self.app.size.width < _NARROW_BELOW)
        # Children mount after on_mount; render/focus on the next refresh.
        self.call_after_refresh(self._initialize_editor)

    def _initialize_editor(self: Any) -> None:
        if not self.is_mounted:
            return
        self._render_all()
        if self._stage == "edit" and self._mode == "cell" and self._cell_editor is None:
            field = self._active_field()
            if field is not None:
                self._mount_cell_editor(field)
        else:
            self.set_focus(None)

    def on_resize(self: Any, event: events.Resize) -> None:
        was_narrow = self.has_class("-narrow")
        self._set_narrow(event.size.width < _NARROW_BELOW)
        if self.is_mounted and was_narrow != self.has_class("-narrow"):
            self._render_all()

    def _set_narrow(self: Any, narrow: bool) -> None:
        self.set_class(narrow, "-narrow")

    def _render_all(self: Any) -> None:
        if not self.is_mounted:
            return
        self.query_one("#axe-editor-title", Static).update(self._title_text())
        self.query_one("#axe-editor-run-status", Static).update(self._status_text())
        self._render_scopes()
        warning = self._seed.generated_warning or ""
        warning_widget = self.query_one("#axe-editor-warning", Static)
        warning_widget.update(
            Text(f"! {warning}", style="bold #FFAF5F") if warning else ""
        )
        warning_widget.display = bool(warning)
        self._render_sheet()
        self._render_detail_dock()
        self._render_status_line()
        self._render_preview()
        self.query_one("#axe-editor-hints", Static).update(self._hints())
        self._sync_visibility()

    def _render_sheet(self: Any) -> None:
        rows = build_sheet_rows(self._form, target=self._target)
        sheet = self.query_one("#axe-editor-sheet", VerticalScroll)
        width = max(30, sheet.content_size.width or self.app.size.width - 10)
        columns = sheet_column_widths(
            rows,
            width=width,
            narrow=self.has_class("-narrow"),
        )
        for index, row in enumerate(rows):
            self._render_sheet_row(index, row, columns)

    def _render_sheet_row(
        self: Any, index: int, row: AxeEntrySheetRow, columns: Any
    ) -> None:
        selected = row.name == self._active_name
        editing = selected and self._mode == "cell" and self._stage == "edit"
        field_row = self.query_one(f"#axe-editor-field-{index}", Horizontal)
        field_row.set_class(selected, "selected")
        field_row.set_class(editing, "editing")
        field_row.set_class(
            editing and row.editor_kind in {"text", "string_list", "yaml"}, "multiline"
        )
        field_row.set_class(row.state == "invalid", "invalid")

        name_widget = self.query_one(f"#axe-editor-name-{index}", Static)
        name_widget.styles.width = columns.name
        name_text = Text(row.name, style="bold #F0C674" if selected else "")
        if row.required:
            name_text.append(" *", style="#F0C674")
        name_widget.update(name_text)

        value_widget = self.query_one(f"#axe-editor-value-text-{index}", Static)
        value_widget.display = not editing or not bool(
            self.query(f"#axe-editor-value-{index} .axe-editor-cell-editor")
        )
        value_style = "dim" if row.dim_value else ""
        if row.state == "invalid":
            value_style = "#FF8787"
        value_widget.update(
            Text(_end_ellipsize(row.value, columns.value), style=value_style)
        )

        badge_widget = self.query_one(f"#axe-editor-badge-{index}", Static)
        badge_widget.styles.width = columns.badge
        badge_widget.display = columns.badge > 0
        badge_widget.update(
            Text(row.badge, style=_BADGE_COLORS.get(row.badge_style, "dim"))
        )

    def _render_detail_dock(self: Any) -> None:
        field = self._active_field()
        mode = self._editor_mode_label if self._mode == "cell" else ""
        header, description, definitions = detail_dock_lines(
            field,
            target=self._target,
            vim_mode=mode,
        )
        header_text = Text()
        if field is None:
            header_text.append(header, style="dim")
        else:
            required = " *" if field.required else ""
            header_text.append(f"{field.name}{required}", style="bold #F0C674")
            header_text.append(f"  {field.editor_kind}", style="#D7A85B")
            if mode:
                header_text.append(f"  {mode}", style="bold #87AFD7")
        self.query_one("#axe-editor-dock-header", Static).update(header_text)
        self.query_one("#axe-editor-dock-description", Static).update(description)
        self.query_one("#axe-editor-dock-values", Static).update(
            Text(definitions, style="dim")
        )

    def _render_status_line(self: Any) -> None:
        value = status_line_text(
            self._active_field(),
            error=self._error,
            status=self._status,
        )
        style = "bold #FF8787" if value.startswith("!") else "dim"
        self.query_one("#axe-editor-status", Static).update(Text(value, style=style))

    def _render_preview(self: Any) -> None:
        preview = self.query_one("#axe-editor-preview", Static)
        if self._stage != "preview":
            preview.update("")
        elif self._busy and self._plan is None:
            preview.update(Text("Planning…", style="#888888"))
        elif self._plan is not None:
            preview.update(
                render_transaction_preview(coerce_transaction_preview(self._plan))
            )
        else:
            preview.update("")

    def _sync_visibility(self: Any) -> None:
        edit = self._stage == "edit"
        self.query_one("#axe-editor-sheet").display = edit
        self.query_one("#axe-editor-dock").display = edit
        self.query_one("#axe-editor-preview-scroll").display = not edit

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
        pending = sum(field.touched for field in self._form.fields)
        if pending:
            noun = "edit" if pending == 1 else "edits"
            text.append(f" · {pending} pending {noun}", style="#D7A85B")
        if self._seed.status:
            text.append(f" · {self._seed.status}", style="dim")
        if self._seed.identity.generated_instance:
            text.append(
                f" · instance {self._seed.identity.generated_instance}",
                style="dim",
            )
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
        width = max(12, path_widget.content_size.width or 36)
        path = _display_path(target.path, max(1, width - len(suffix)))
        text = Text(path, style="dim")
        if suffix:
            text.append(suffix, style="#FFAF5F")
        path_widget.update(text)

    def _set_editor_mode_label(self: Any, value: str) -> None:
        if value == self._editor_mode_label:
            return
        self._editor_mode_label = value
        if self.is_mounted:
            self._render_detail_dock()

    def _hints(self: Any) -> str:
        return hint_text(
            mode=self._mode,
            stage=self._stage,
            running=self._seed.running,
            busy=self._busy,
            narrow=self.has_class("-narrow"),
        )

    @staticmethod
    def _field_editor_text(field: SchemaObjectField | None) -> str:
        if field is None:
            return ""
        if field.draft_text is not None:
            return field.draft_text
        return format_value_for_editor(field.editor_kind, field.draft_value)


__all__ = [
    "AxeEntryEditorRenderingMixin",
    "AxeValueInput",
    "AxeValueTextArea",
    "_HOME",
    "_display_path",
]
