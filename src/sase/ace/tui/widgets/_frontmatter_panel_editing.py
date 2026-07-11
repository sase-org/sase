"""Schema-driven in-panel editing for :class:`FrontmatterPanel`."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.ace.tui.widgets._local_xprompt_conversion import (
    normalize_local_xprompt_name,
    validate_local_xprompt_name,
)
from sase.xprompt.frontmatter_schema import FrontmatterFieldKind, input_type_schema
from sase.xprompt.loader_parsing import parse_input_type
from sase.xprompt.models import UNSET, InputArg, XPrompt, XPromptValidationError
from sase.xprompt.prompt_frontmatter import (
    FrontmatterStateValue,
    FrontmatterValueState,
    LOCAL_XPROMPT_SOURCE,
    PromptFrontmatter,
)

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object

_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_UNDO_LIMIT = 50


@dataclass
class _CellEdit:
    field: str
    item_kind: str
    cells: tuple[str, ...]
    values: dict[str, str]
    original_name: str | None = None
    index: int = 0
    ghost: bool = False
    on_commit: Callable[[XPrompt], None] | None = None

    @property
    def active_cell(self) -> str:
        return self.cells[self.index]


class _FrontmatterFieldDescriptor(Protocol):
    name: str
    kind: FrontmatterFieldKind
    required: bool
    description: str
    allowed_values: str | None
    example: str


def _default_to_text(default: Any) -> str:
    if default is UNSET:
        return ""
    if isinstance(default, bool):
        return "true" if default else "false"
    return str(default)


class FrontmatterPanelEditingMixin(_MixinBase):
    """All mutations stay inside the panel and are snapshot-undoable."""

    if TYPE_CHECKING:
        AddRequested: type[Any]
        Changed: type[Any]
        Closed: type[Any]
        _adding_field: str | None
        _cell_edit: _CellEdit | None
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

    def _begin_value_state_edit(self, field: str) -> None:
        current = self._model.value_state(field)
        state = current.state.value
        if current.state is FrontmatterValueState.PAYLOAD:
            state = (
                "providers…"
                if self._schema[field].kind is FrontmatterFieldKind.BOOL_OR_LIST
                else "trigger…"
            )
        payload = current.payload
        payload_text = (
            ", ".join(payload) if isinstance(payload, list) else str(payload or "")
        )
        self._cell_edit = _CellEdit(
            field=field,
            item_kind="value_state",
            cells=("state", "payload"),
            values={"state": state, "payload": payload_text},
        )
        self._activate_cell()

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

    # -- structured cell editing ---------------------------------------

    def _begin_cell_edit(
        self,
        field: str,
        *,
        item_name: str | None = None,
        ghost: bool = False,
        prefill: XPrompt | None = None,
        on_commit: Callable[[XPrompt], None] | None = None,
    ) -> None:
        item_kind = self._structured_item_kind(field)
        if item_kind == "input":
            arg = self._model.get_input(item_name or "")
            values = {
                "name": arg.name if arg else "",
                "type": arg.type.value if arg else "line",
                "default": _default_to_text(arg.default) if arg else "",
                "description": arg.description or "" if arg else "",
            }
            cells = ("name", "type", "default", "description")
        else:
            xprompt = prefill or self._model.get_xprompt(item_name or "")
            values = {
                "name": xprompt.name if xprompt else "_",
                "description": xprompt.description or "" if xprompt else "",
                "inputs": self._format_compact_inputs(xprompt.inputs)
                if xprompt
                else "",
                "content": xprompt.content if xprompt else "",
            }
            cells = ("name", "description", "inputs", "content")
        self._cell_edit = _CellEdit(
            field=field,
            item_kind=item_kind,
            cells=cells,
            values=values,
            original_name=item_name,
            ghost=ghost,
            on_commit=on_commit,
        )
        self._adding_field = field if field not in self._fields else None
        self._folded.discard(field)
        if ghost:
            self._select_nav((item_kind, "__ghost__"))
        self._activate_cell()

    def begin_prefilled_xprompt(
        self,
        field: str,
        xprompt: XPrompt,
        *,
        on_commit: Callable[[XPrompt], None] | None = None,
    ) -> None:
        """Public bridge used by ``gX`` to enter the same ghost-row flow."""
        self._begin_cell_edit(field, ghost=True, prefill=xprompt, on_commit=on_commit)

    def _activate_cell(self) -> None:
        cell = self._cell_edit
        if cell is None:
            return
        self._feedback = ""
        if cell.active_cell == "content":
            self._edit_mode = "content"
            editor = self.query_one("#frontmatter-content", VimTextArea)
            editor.text = cell.values["content"]
            editor.border_title = "content"
            self.query_one("#frontmatter-inline", SingleLineVimTextArea).add_class(
                "hidden"
            )
            editor.remove_class("hidden")
            self._refresh()
            self._schedule_layout_update()  # type: ignore[attr-defined]
            editor.focus()
            editor._update_vim_mode_display()
            return
        self._edit_mode = "cell"
        editor = self.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = cell.values[cell.active_cell]
        editor.border_title = cell.active_cell
        self.query_one("#frontmatter-content", VimTextArea).add_class("hidden")
        editor.remove_class("hidden")
        self._refresh_cell_feedback()
        self._refresh()
        self._schedule_layout_update()  # type: ignore[attr-defined]
        editor.focus()
        editor.cursor_position = len(editor.text)
        editor._update_vim_mode_display()

    def _capture_active_cell(self) -> None:
        cell = self._cell_edit
        if cell is None:
            return
        if self._edit_mode == "content":
            value = self.query_one("#frontmatter-content", VimTextArea).text
        else:
            value = self.query_one("#frontmatter-inline", SingleLineVimTextArea).text
        if cell.item_kind == "xprompt" and cell.active_cell == "name":
            value = normalize_local_xprompt_name(value)
        cell.values[cell.active_cell] = value

    def _move_cell(self, delta: int) -> None:
        cell = self._cell_edit
        if cell is None:
            return
        self._capture_active_cell()
        cell.index = (cell.index + delta) % len(cell.cells)
        self._activate_cell()

    def _cycle_active_cell(self, delta: int) -> bool:
        cell = self._cell_edit
        if cell is None:
            return False
        if cell.item_kind == "input" and cell.active_cell == "type":
            choices = [descriptor.name for descriptor in input_type_schema()]
        elif cell.item_kind == "value_state" and cell.active_cell == "state":
            choices = ["true", "false"]
            choices.append(
                "providers…"
                if self._schema[cell.field].kind is FrontmatterFieldKind.BOOL_OR_LIST
                else "trigger…"
            )
        else:
            return False
        current = cell.values[cell.active_cell]
        index = choices.index(current) if current in choices else 0
        value = choices[(index + delta) % len(choices)]
        cell.values[cell.active_cell] = value
        editor = self.query_one("#frontmatter-inline", SingleLineVimTextArea)
        editor.text = value
        editor.cursor_position = len(value)
        self._refresh_cell_feedback()
        self._refresh()
        return True

    def _refresh_cell_feedback(self) -> None:
        cell = self._cell_edit
        if cell is None:
            self._feedback = ""
            return
        self._capture_active_cell()
        if cell.item_kind == "input" and cell.active_cell == "type":
            typed = cell.values["type"].strip().casefold()
            matches = [
                descriptor
                for descriptor in input_type_schema()
                if descriptor.name.startswith(typed)
                or any(alias.startswith(typed) for alias in descriptor.aliases)
            ]
            if typed and len(matches) == 1:
                cell.values["type"] = matches[0].name
                self._feedback = matches[0].rule
            else:
                self._feedback = (
                    "unknown or ambiguous input type"
                    if typed
                    else "Choose an input type"
                )
            return
        _, error = self._build_cell_result()
        self._feedback = error

    def _commit_cell_edit(self) -> None:
        self._capture_active_cell()
        result, error = self._build_cell_result()
        if result is None:
            self._feedback = error
            self._refresh()
            return
        cell = self._cell_edit
        assert cell is not None
        self._push_undo()
        if cell.item_kind == "input":
            assert isinstance(result, InputArg)
            if cell.original_name and cell.original_name != result.name:
                self._model.remove_input(cell.original_name)
            self._model.set_input(result)
            selected = ("input", result.name)
        elif cell.item_kind == "xprompt":
            assert isinstance(result, XPrompt)
            if cell.original_name and cell.original_name != result.name:
                self._model.remove_xprompt(cell.original_name)
            self._model.set_xprompt(result)
            selected = ("xprompt", result.name)
        else:
            assert isinstance(result, FrontmatterStateValue)
            self._model.set_value_state(cell.field, result)
            selected = ("field", cell.field)
        callback = cell.on_commit
        xprompt_result = result if isinstance(result, XPrompt) else None
        self._cell_edit = None
        self._adding_field = None
        self._edit_mode = "rows"
        self._show_rows_only()
        self._fields = self._model.present_fields()
        self._select_nav(selected)
        self._feedback = "Saved"
        self._refresh()
        self.call_after_refresh(self.focus)
        self._schedule_layout_update()  # type: ignore[attr-defined]
        self._emit_changed()
        if callback is not None and xprompt_result is not None:
            callback(xprompt_result)

    def _build_cell_result(
        self,
    ) -> tuple[InputArg | XPrompt | FrontmatterStateValue | None, str]:
        cell = self._cell_edit
        if cell is None:
            return None, "no active edit"
        if cell.item_kind == "value_state":
            state = cell.values["state"]
            if state == "true":
                return FrontmatterStateValue(FrontmatterValueState.TRUE), ""
            if state == "false":
                return FrontmatterStateValue(FrontmatterValueState.FALSE), ""
            payload = cell.values["payload"].strip()
            if not payload:
                return None, "payload is required for this state"
            if self._schema[cell.field].kind is FrontmatterFieldKind.BOOL_OR_LIST:
                return FrontmatterStateValue(
                    FrontmatterValueState.PAYLOAD,
                    [part.strip() for part in payload.split(",") if part.strip()],
                ), ""
            return FrontmatterStateValue(FrontmatterValueState.PAYLOAD, payload), ""

        name = cell.values["name"].strip()
        if not name:
            return None, "name is required"
        if not _NAME_RE.fullmatch(name):
            return None, "name must be a valid identifier"

        if cell.item_kind == "input":
            used = {
                arg.name for arg in self._model.inputs if arg.name != cell.original_name
            }
            if name in used:
                return None, f"input '{name}' already exists"
            descriptor = self._resolve_input_type(cell.values["type"])
            if descriptor is None:
                return None, f"unknown input type '{cell.values['type'].strip()}'"
            input_type = parse_input_type(descriptor.name)
            default_text = cell.values["default"].strip()
            default: Any = UNSET
            if default_text:
                try:
                    default = InputArg(name=name, type=input_type).validate_and_convert(
                        default_text
                    )
                except XPromptValidationError as exc:
                    return None, str(exc)
            return InputArg(
                name=name,
                type=input_type,
                default=default,
                description=cell.values["description"].strip() or None,
            ), ""

        name = normalize_local_xprompt_name(name)
        used = set(self._model.xprompts) - (
            {cell.original_name} if cell.original_name else set()
        )
        error = validate_local_xprompt_name(name, used)
        if error:
            return None, error
        content = cell.values["content"].strip()
        if not content:
            return None, "content is required"
        try:
            inputs = self._parse_compact_inputs(cell.values["inputs"])
        except ValueError as exc:
            return None, str(exc)
        return XPrompt(
            name=name,
            content=content,
            inputs=inputs,
            source_path=LOCAL_XPROMPT_SOURCE,
            description=cell.values["description"].strip() or None,
        ), ""

    @staticmethod
    def _resolve_input_type(text: str) -> Any | None:
        typed = text.strip().casefold()
        exact = []
        prefix = []
        for descriptor in input_type_schema():
            spellings = (descriptor.name, *descriptor.aliases)
            if typed in spellings:
                exact.append(descriptor)
            elif any(spelling.startswith(typed) for spelling in spellings):
                prefix.append(descriptor)
        choices = exact or prefix
        return choices[0] if len(choices) == 1 else None

    @classmethod
    def _parse_compact_inputs(cls, text: str) -> list[InputArg]:
        inputs: list[InputArg] = []
        seen: set[str] = set()
        for chunk in text.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            spec, has_default, default_text = chunk.partition("=")
            name, _, type_text = spec.partition(":")
            name = name.strip()
            descriptor = cls._resolve_input_type(type_text.strip() or "line")
            if not _NAME_RE.fullmatch(name):
                raise ValueError(f"invalid input name '{name}'")
            if name in seen:
                raise ValueError(f"duplicate input '{name}'")
            if descriptor is None:
                raise ValueError(f"unknown input type '{type_text.strip()}'")
            input_type = parse_input_type(descriptor.name)
            default: Any = UNSET
            if has_default:
                try:
                    default = InputArg(name=name, type=input_type).validate_and_convert(
                        default_text.strip()
                    )
                except XPromptValidationError as exc:
                    raise ValueError(str(exc)) from None
            seen.add(name)
            inputs.append(InputArg(name=name, type=input_type, default=default))
        return inputs

    @staticmethod
    def _format_compact_inputs(inputs: list[InputArg]) -> str:
        result: list[str] = []
        for arg in inputs:
            text = f"{arg.name}:{arg.type.value}"
            if arg.default is not UNSET:
                text += f"={_default_to_text(arg.default)}"
            result.append(text)
        return ", ".join(result)

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

    def _close(self) -> None:
        self.post_message(self.Closed(is_empty=self._model.is_empty))

    def _emit_changed(self) -> None:
        # Once a structured mutation is persisted, the original commented YAML
        # is no longer an accurate editing buffer; subsequent raw mode must show
        # the current canonical state instead of stale pre-edit values.
        self._model.original_text = ""
        self._model.has_comments = False
        self.post_message(self.Changed(self._model))
