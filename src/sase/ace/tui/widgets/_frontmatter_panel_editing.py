"""Schema-driven in-panel editing for :class:`FrontmatterPanel`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from textual.widgets import Static, TextArea

from sase.ace.tui.widgets._frontmatter_panel_cell_editing import (
    FrontmatterPanelCellEditingMixin,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.frontmatter_schema import FrontmatterFieldKind
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

_UNDO_LIMIT = 50


class _FrontmatterFieldDescriptor(Protocol):
    name: str
    kind: FrontmatterFieldKind
    required: bool
    description: str
    allowed_values: str | None
    example: str


class FrontmatterPanelEditingMixin(FrontmatterPanelCellEditingMixin):
    """All mutations stay inside the panel and are snapshot-undoable."""

    if TYPE_CHECKING:
        AddRequested: type[Any]
        Changed: type[Any]
        Closed: type[Any]
        _adding_field: str | None
        _cell_edit: Any | None
        _edit_mode: str
        _editing_field: str | None
        _feedback: str
        _fields: list[str]
        _folded: set[str]
        _model: PromptFrontmatter
        _picker_matches: list[str]
        _picker_selected: int
        _picker_accelerators: dict[str, str]
        _schema: dict[str, Any]
        _schema_order: list[str]
        _selected: int
        _undo_stack: list[PromptFrontmatter]

        def _clamp_selection(self) -> None: ...
        def _nav_rows(self) -> list[tuple[str, str]]: ...
        def _refresh(self) -> None: ...
        def _row_fields(self) -> list[str]: ...
        def _select_nav(self, target: tuple[str, str]) -> None: ...
        def _selected_nav(self) -> tuple[str, str] | None: ...

    # -- schema/catalog --------------------------------------------------

    def addable_properties(self) -> list[_FrontmatterFieldDescriptor]:
        return [
            self._schema[name]
            for name in self._schema_order
            if name not in self._fields
        ]

    def _structured_item_kind(self, field: str) -> str:
        """Infer the structured item catalog from the model container shape."""
        return (
            "input" if isinstance(self._model.field_value(field), list) else "xprompt"
        )

    # -- snapshots -------------------------------------------------------

    def _push_undo(self) -> None:
        snapshot = PromptFrontmatter.parse(self._model.serialize())
        snapshot.original_text = self._model.original_text
        snapshot.has_comments = self._model.has_comments
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > _UNDO_LIMIT:
            del self._undo_stack[0]

    def _undo(self) -> None:
        if not self._undo_stack:
            self._feedback = "Nothing to undo"
            self._refresh()
            return
        self._model = self._undo_stack.pop()
        self._fields = self._model.present_fields()
        self._cell_edit = None
        self._adding_field = None
        self._edit_mode = "rows"
        self._show_rows_only()
        self._clamp_selection()
        self._feedback = "Undid last frontmatter change"
        self._refresh()
        self._emit_changed()

    # -- add picker ------------------------------------------------------

    def begin_add(self, field: str) -> None:
        if field not in self._schema or field in self._fields:
            return
        if self._schema[field].kind is FrontmatterFieldKind.STRUCTURED:
            self._begin_cell_edit(field, ghost=True)
            return
        self._adding_field = field
        self._begin_inline_edit(field, initial="", adding=True)

    def _request_add_property(self) -> None:
        if not self.addable_properties():
            self._feedback = "Every schema property is already present"
            self._refresh()
            return
        self._edit_mode = "picker"
        self._editing_field = None
        self._adding_field = None
        self._picker_selected = 0
        used: set[str] = set()
        self._picker_accelerators = {}
        for descriptor in self.addable_properties():
            candidates = [
                character.casefold()
                for character in descriptor.name
                if character.isalnum()
                and character.casefold() not in {"j", "k", "q"}
                and character.casefold() not in used
            ]
            if not candidates:
                continue
            accelerator = candidates[0]
            used.add(accelerator)
            self._picker_accelerators[accelerator] = descriptor.name
        self._update_picker("")
        editor = self.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = ""
        editor.border_title = "add property"
        editor.remove_class("hidden")
        self._refresh()
        self._schedule_layout_update()  # type: ignore[attr-defined]
        editor.focus()
        editor._update_vim_mode_display()

    def _update_picker(self, query: str) -> None:
        needle = query.strip().casefold()
        names = [descriptor.name for descriptor in self.addable_properties()]
        self._picker_matches = [name for name in names if needle in name.casefold()]
        self._picker_selected = min(
            self._picker_selected, max(0, len(self._picker_matches) - 1)
        )
        self._refresh()

    def _commit_picker(self) -> None:
        if not self._picker_matches:
            self._feedback = "No matching schema property"
            self._refresh()
            return
        field = self._picker_matches[self._picker_selected]
        self._finish_inline_edit()
        self.begin_add(field)

    # -- row commands ----------------------------------------------------

    def _add_item_at_selection(self) -> None:
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        if kind == "field":
            schema = self._schema.get(key)
            if schema is None or schema.kind is not FrontmatterFieldKind.STRUCTURED:
                return
            field = key
        elif kind in {"input", "xprompt"}:
            field = next(
                (
                    candidate
                    for candidate in self._row_fields()
                    if self._schema.get(candidate) is not None
                    and self._schema[candidate].kind is FrontmatterFieldKind.STRUCTURED
                    and self._structured_item_kind(candidate) == kind
                ),
                "",
            )
        else:
            return
        if field:
            self._begin_cell_edit(field, ghost=True)

    def _edit_selected(self) -> None:
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        if kind in {"input", "xprompt"}:
            field = next(
                candidate
                for candidate in self._row_fields()
                if self._schema.get(candidate) is not None
                and self._schema[candidate].kind is FrontmatterFieldKind.STRUCTURED
                and self._structured_item_kind(candidate) == kind
            )
            self._begin_cell_edit(field, item_name=key)
            return
        schema = self._schema.get(key)
        if schema is None:  # passthrough extras are raw-only
            self._feedback = f"{key} is passthrough data; edit it in raw mode"
            self._refresh()
            return
        if schema.kind is FrontmatterFieldKind.STRUCTURED:
            if key in self._folded:
                self._folded.discard(key)
            else:
                self._folded.add(key)
            self._refresh()
            return
        if schema.kind in {
            FrontmatterFieldKind.BOOL_OR_LIST,
            FrontmatterFieldKind.BOOL_OR_SCALAR,
        }:
            self._begin_value_state_edit(key)
            return
        self._begin_inline_edit(key, initial=self._editable_text(key))

    def _delete_selected(self) -> None:
        nav = self._selected_nav()
        if nav is None:
            return
        kind, key = nav
        if kind == "field" and key not in self._schema:
            self._feedback = f"{key} is read-only here; use raw mode"
            self._refresh()
            return
        self._push_undo()
        if kind == "input":
            self._model.remove_input(key)
        elif kind == "xprompt":
            self._model.remove_xprompt(key)
        else:
            self._model.clear_field(key)
        self._after_mutation()

    def _move_selected_item(self, delta: int) -> None:
        nav = self._selected_nav()
        if nav is None or nav[0] not in {"input", "xprompt"}:
            return
        kind, name = nav
        self._push_undo()
        if kind == "input":
            names = [arg.name for arg in self._model.inputs]
            index = names.index(name)
            target = max(0, min(index + delta, len(names) - 1))
            if target == index:
                self._undo_stack.pop()
                return
            item = self._model.inputs.pop(index)
            self._model.inputs.insert(target, item)
        else:
            entries = list(self._model.xprompts.items())
            index = next(
                i for i, (entry_name, _) in enumerate(entries) if entry_name == name
            )
            target = max(0, min(index + delta, len(entries) - 1))
            if target == index:
                self._undo_stack.pop()
                return
            entry = entries.pop(index)
            entries.insert(target, entry)
            self._model.xprompts = dict(entries)
        self._fields = self._model.present_fields()
        self._select_nav((kind, name))
        self._feedback = f"Moved {name} {'down' if delta > 0 else 'up'}"
        self._refresh()
        self._emit_changed()

    # -- scalar and bool-state editing ----------------------------------

    def _begin_inline_edit(
        self, field: str, *, initial: str, adding: bool = False
    ) -> None:
        self._edit_mode = "edit"
        self._editing_field = field
        if not adding:
            self._adding_field = None
        editor = self.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = initial
        editor.border_title = field
        editor.remove_class("hidden")
        self._refresh()
        self._schedule_layout_update()  # type: ignore[attr-defined]
        editor.focus()
        editor.cursor_position = len(editor.text)
        editor._update_vim_mode_display()

    def _editable_text(self, field: str) -> str:
        value = self._model.field_value(field)
        kind = self._schema[field].kind
        if value is None:
            return ""
        if kind is FrontmatterFieldKind.LIST:
            return ", ".join(str(item) for item in value)
        return str(value)

    def _apply_inline_value(self, field: str, raw_text: str) -> None:
        text = raw_text.strip()
        if not text:
            self._model.clear_field(field)
            return
        kind = self._schema[field].kind
        if kind is FrontmatterFieldKind.SCALAR:
            setattr(self._model, field, text)
        elif kind is FrontmatterFieldKind.LIST:
            setattr(
                self._model,
                field,
                [part.strip() for part in text.split(",") if part.strip()],
            )

    # -- shared editor lifecycle ---------------------------------------

    def _cancel_active_edit(self) -> None:
        self._cell_edit = None
        self._adding_field = None
        self._picker_matches = []
        self._feedback = ""
        self._finish_inline_edit()

    def _cancel_inline_edit(self) -> None:
        self._cancel_active_edit()

    def _finish_inline_edit(self) -> None:
        self._edit_mode = "rows"
        self._editing_field = None
        self.query_one("#frontmatter-inline", SingleLineVimTextArea).add_class("hidden")
        self.query_one("#frontmatter-content", VimTextArea).add_class("hidden")
        self._fields = self._model.present_fields()
        self._clamp_selection()
        self._refresh()
        self.focus()
        self._schedule_layout_update()  # type: ignore[attr-defined]

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        if event.text_area.id != "frontmatter-inline":
            return
        event.stop()
        if self._edit_mode == "picker":
            self._commit_picker()
            return
        if self._edit_mode == "cell":
            self._commit_cell_edit()
            return
        field = self._editing_field
        if field is not None:
            self._push_undo()
            self._apply_inline_value(field, event.value)
        self._adding_field = None
        self._finish_inline_edit()
        self._emit_changed()

    def _show_rows_only(self) -> None:
        self.query_one("#frontmatter-rows", Static).remove_class("hidden")
        self.query_one("#frontmatter-inline", SingleLineVimTextArea).add_class("hidden")
        self.query_one("#frontmatter-raw", TextArea).add_class("hidden")
        self.query_one("#frontmatter-content", TextArea).add_class("hidden")

    def _after_mutation(self) -> None:
        self._fields = self._model.present_fields()
        self._clamp_selection()
        self._feedback = ""
        self._refresh()
        self._emit_changed()

    def _close(self, *, focus_target: str = "active") -> None:
        self.post_message(
            self.Closed(
                is_empty=self._model.is_empty,
                focus_target=focus_target,
            )
        )

    def _emit_changed(self) -> None:
        # Once a structured mutation is persisted, the original commented YAML
        # is no longer an accurate editing buffer; subsequent raw mode must show
        # the current canonical state instead of stale pre-edit values.
        self._model.original_text = ""
        self._model.has_comments = False
        self.post_message(self.Changed(self._model))
