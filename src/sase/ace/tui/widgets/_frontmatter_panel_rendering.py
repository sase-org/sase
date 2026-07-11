"""Rendering, navigation rows, and diagnostics for ``FrontmatterPanel``."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from rich.text import Text
import yaml  # type: ignore[import-untyped]

from sase.xprompt.frontmatter_schema import (
    FrontmatterDiagnostic,
    FrontmatterFieldKind,
)
from sase.xprompt.models import UNSET, InputArg, XPrompt

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase

    from sase.xprompt.prompt_frontmatter import PromptFrontmatter

else:
    _MixinBase = object

# A top-level YAML key line in the serialized block (column-0 ``key:``), used to
# attribute a core diagnostic's line back to the field row it belongs under.
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):")

# Width of the key column so value summaries align, matching the design mockups.
_KEY_COLUMN = 13

_SUBTITLE_POPULATED = "a property · o item · e edit · d del · u undo · J/K move · R raw"
_SUBTITLE_EMPTY = "a property · R raw · esc done"
_SUBTITLE_EDIT = "enter save · esc esc cancel"
_SUBTITLE_CELL = "tab/shift+tab cell · enter save · esc esc cancel"
_SUBTITLE_CONTENT = "ctrl+s save row · shift+tab previous · esc esc cancel"
_SUBTITLE_PICKER = "type to filter · enter add · esc esc cancel"
_SUBTITLE_RAW = "esc esc apply · ctrl+c discard · live-validated"


class FrontmatterPanelRenderingMixin(_MixinBase):
    """Rows view rendering and diagnostic attribution for the panel."""

    if TYPE_CHECKING:
        _adding_field: str | None
        _cell_edit: Any | None
        _content_lines: int
        _edit_mode: str
        _feedback: str
        _fields: list[str]
        _folded: set[str]
        _model: PromptFrontmatter
        _picker_matches: list[str]
        _picker_selected: int
        _schema: dict[str, Any]
        _schema_order: list[str]
        _selected: int

        def _editable_text(self, field: str) -> str: ...
        def _selected_nav(self) -> tuple[str, str] | None: ...
        def _structured_item_kind(self, field: str) -> str: ...

    def _refresh(self) -> None:
        """Rebuild the rows renderable, status chip, and subtitle."""
        from textual.widgets import Static

        rows = self.query_one("#frontmatter-rows", Static)
        renderable, line_count = self._build_rows()
        rows.update(renderable)
        if self._edit_mode == "rows":
            rows.scroll_to(y=max(0, self._selected - 1), animate=False)
        self._content_lines = line_count
        feedback = self.query_one("#frontmatter-feedback", Static)
        if self._feedback and self._edit_mode != "raw":
            error_words = (
                "required",
                "invalid",
                "unknown",
                "duplicate",
                "exists",
                "expects",
            )
            style = (
                "red"
                if any(word in self._feedback.casefold() for word in error_words)
                else "dim"
            )
            feedback.update(Text(self._feedback, style=style))
            feedback.remove_class("hidden")
        elif self._edit_mode != "raw":
            feedback.update("")
            feedback.add_class("hidden")
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        """Update the border title chip and the keymap subtitle for the mode."""
        diagnostics = self._diagnostics()
        errors = sum(1 for d in diagnostics if d.is_error)
        if self._model.is_empty:
            chip = "[dim]⟨ ⟩[/]"
        elif errors:
            chip = f"[bold red]⟨! {errors}⟩[/]"
        else:
            chip = "[bold green]⟨✓⟩[/]"
        self.border_title = f"frontmatter  {chip}"
        if self._edit_mode == "edit":
            self.border_subtitle = _SUBTITLE_EDIT
        elif self._edit_mode == "cell":
            self.border_subtitle = _SUBTITLE_CELL
        elif self._edit_mode == "content":
            self.border_subtitle = _SUBTITLE_CONTENT
        elif self._edit_mode == "picker":
            self.border_subtitle = _SUBTITLE_PICKER
        elif self._edit_mode == "raw":
            self.border_subtitle = _SUBTITLE_RAW
        elif self._model.is_empty:
            self.border_subtitle = _SUBTITLE_EMPTY
        else:
            self.border_subtitle = _SUBTITLE_POPULATED

    def _build_rows(self) -> tuple[Text, int]:
        """Return the rows renderable and its rendered line count."""
        if (
            self._model.is_empty
            and self._adding_field is None
            and self._edit_mode != "picker"
        ):
            text = self._empty_state()
            return text, len(text.plain.splitlines()) or 1

        field_errors = self._diagnostics_by_field()
        selected = None if self._edit_mode == "raw" else self._selected_nav()
        lines: list[Text] = []
        for field in self._row_fields():
            lines.extend(self._render_field(field, selected=selected))
            for message in field_errors.get(field, ()):  # inline core guidance
                error = Text("      ")
                error.append(message, style="red")
                lines.append(error)
        if self._edit_mode == "picker":
            picker = Text("  add  ", style="bold #87D7FF")
            if not self._picker_matches:
                picker.append("(no matches)", style="red")
            else:
                for index, name in enumerate(self._picker_matches):
                    if index:
                        picker.append(" · ", style="dim")
                    picker.append(
                        name,
                        style="bold reverse #87D7FF"
                        if index == self._picker_selected
                        else "dim",
                    )
            lines.append(picker)
        group = Text("\n").join(lines)
        return group, len(lines) or 1

    def _row_fields(self) -> list[str]:
        """Present fields plus the in-progress add row (canonical order)."""
        fields = list(self._fields)
        if self._adding_field is not None and self._adding_field not in fields:
            fields.append(self._adding_field)
        return fields

    def _nav_rows(self) -> list[tuple[str, str]]:
        """Flat list of navigable rows: field headers and unfolded sub-items.

        Each entry is ``("field", name)`` for a property row, or
        ``("input", arg_name)`` / ``("xprompt", name)`` for a sub-item of an
        unfolded structured field.  Selection (:attr:`_selected`) indexes into
        this list so ``j``/``k`` step through items as well as fields.
        """
        rows: list[tuple[str, str]] = []
        for field in self._row_fields():
            rows.append(("field", field))
            schema = self._schema.get(field)
            if schema is None or schema.kind is not FrontmatterFieldKind.STRUCTURED:
                continue
            if field in self._folded:
                continue
            item_kind = self._structured_item_kind(field)
            if item_kind == "input":
                rows.extend(("input", arg.name) for arg in self._model.inputs)
            else:
                rows.extend(("xprompt", name) for name in self._model.xprompts)
            if (
                self._cell_edit is not None
                and self._cell_edit.field == field
                and self._cell_edit.ghost
            ):
                rows.append((item_kind, "__ghost__"))
        return rows

    def _empty_state(self) -> Text:
        """The just-triggered empty panel guidance."""
        text = Text()
        text.append("No properties yet.\n", style="dim")
        text.append("Press ", style="dim")
        text.append("a", style="bold #87D7FF")
        text.append(" to add:\n", style="dim")
        entries: list[str] = []
        for name in self._schema_order:
            descriptor = self._schema[name]
            example = descriptor.example
            if len(example) > 28:
                example = example[:27] + "…"
            entries.append(f"{name} ({example})")
        for index in range(0, len(entries), 2):
            text.append("  " + "  ·  ".join(entries[index : index + 2]), style="dim")
            if index + 2 < len(entries):
                text.append("\n")
        return text

    def _render_field(
        self, field: str, *, selected: tuple[str, str] | None
    ) -> list[Text]:
        """Render one field row (plus its sub-items when unfolded)."""
        schema = self._schema.get(field)
        structured = (
            schema is not None and schema.kind is FrontmatterFieldKind.STRUCTURED
        )
        header_selected = selected == ("field", field)
        marker = "▸ " if header_selected else "  "
        key_style = "bold reverse #87D7FF" if header_selected else "bold #87D7FF"
        row = Text(marker)
        row.append(field.ljust(_KEY_COLUMN), style=key_style)
        if schema is None:
            row.append(self._extra_value_summary(field))
            if field in self._model.extras:
                row.append("  (raw-only)", style="dim italic")
            return [row]
        if structured:
            folded = field in self._folded
            row.append("▸ " if folded else "▾ ", style="cyan")
            value = self._model.field_value(field)
            count = len(value)
            label = "item" if count == 1 else "items"
            row.append(f"{count} {label}", style="dim")
            rows = [row]
            if not folded:
                rows.extend(self._render_sub_items(field, selected=selected))
            return rows
        if self._cell_edit is not None and self._cell_edit.field == field:
            row.append(self._cell_strip(self._cell_edit))
        else:
            row.append(self._value_summary(field))
        return [row]

    def _render_sub_items(
        self, field: str, *, selected: tuple[str, str] | None
    ) -> list[Text]:
        """Render the sub-item lines for ``input`` / ``xprompts``."""
        lines: list[Text] = []
        item_kind = self._structured_item_kind(field)
        if item_kind == "input":
            name_width = max(
                [len(arg.name) for arg in self._model.inputs]
                + (
                    [len(self._cell_edit.values["name"])]
                    if self._cell_edit and self._cell_edit.field == field
                    else [1]
                )
            )
            type_width = max(
                [len(arg.type.value) for arg in self._model.inputs]
                + (
                    [len(self._cell_edit.values["type"])]
                    if self._cell_edit and self._cell_edit.field == field
                    else [1]
                )
            )
            for arg in self._model.inputs:
                if (
                    self._cell_edit is not None
                    and self._cell_edit.original_name == arg.name
                ):
                    lines.append(self._cell_item_line(self._cell_edit, selected=True))
                else:
                    lines.append(
                        self._input_item_line(
                            arg,
                            selected=selected == ("input", arg.name),
                            name_width=name_width,
                            type_width=type_width,
                        )
                    )
        else:
            for name, xprompt in self._model.xprompts.items():
                if (
                    self._cell_edit is not None
                    and self._cell_edit.original_name == name
                ):
                    lines.append(self._cell_item_line(self._cell_edit, selected=True))
                else:
                    lines.append(
                        self._xprompt_item_line(
                            name, xprompt, selected=selected == ("xprompt", name)
                        )
                    )
        if (
            self._cell_edit is not None
            and self._cell_edit.field == field
            and self._cell_edit.ghost
        ):
            lines.append(self._cell_item_line(self._cell_edit, selected=True))
        if not lines:
            empty = Text("    • ")
            empty.append("(none)", style="dim italic")
            lines.append(empty)
        return lines

    @staticmethod
    def _input_item_line(
        arg: InputArg,
        *,
        selected: bool = False,
        name_width: int = 1,
        type_width: int = 1,
    ) -> Text:
        """One ``input`` sub-item: name, type, required/default, description."""
        line = Text("    • ")
        line.append(
            arg.name.ljust(name_width),
            style="reverse #87D7FF" if selected else "#87D7FF",
        )
        line.append(f"  {arg.type.value.ljust(type_width)}", style="green")
        if arg.default is UNSET:
            line.append("  (required)", style="yellow")
        else:
            line.append(f"  = {arg.default!r}", style="dim")
        if arg.description:
            line.append(f"  {arg.description}", style="dim")
        return line

    @staticmethod
    def _xprompt_item_line(
        name: str, xprompt: XPrompt, *, selected: bool = False
    ) -> Text:
        """One ``xprompts`` sub-item: name and a content/description preview."""
        line = Text("    • ")
        line.append(name, style="reverse #87D7FF" if selected else "#87D7FF")
        preview = xprompt.description or xprompt.content
        preview = " ".join(preview.split())
        if len(preview) > 48:
            preview = f"{preview[:45]}…"
        if preview:
            line.append(f'  "{preview}"', style="dim")
        return line

    def _value_summary(self, field: str) -> Text:
        """Type-styled summary of a scalar / list / bool field's value."""
        value = self._editable_text(field)
        if not value:
            return Text("(empty)", style="dim italic")
        return Text(value, style="white")

    def _extra_value_summary(self, field: str) -> Text:
        value = self._model.extras.get(field, self._model.field_value(field))
        summary = yaml.safe_dump(
            value, default_flow_style=True, sort_keys=False
        ).strip()
        if len(summary) > 52:
            summary = summary[:49] + "…"
        return Text(summary, style="dim")

    @staticmethod
    def _cell_strip(cell: Any) -> Text:
        text = Text()
        for index, name in enumerate(cell.cells):
            if index:
                text.append("  ", style="dim")
            value = cell.values.get(name, "") or "(empty)"
            style = "bold reverse #87D7FF" if index == cell.index else "white"
            text.append(f"{name}:{value}", style=style)
        return text

    def _cell_item_line(self, cell: Any, *, selected: bool) -> Text:
        line = Text("    ◌ " if cell.ghost else "    • ")
        line.append(self._cell_strip(cell))
        return line

    def _diagnostics(self) -> list[FrontmatterDiagnostic]:
        """Core validation diagnostics for the current model (may be empty)."""
        try:
            return self._model.diagnostics()
        except Exception:
            return []

    def _diagnostics_by_field(self) -> dict[str, list[str]]:
        """Map each error diagnostic to the top-level field row it falls under."""
        diagnostics = [d for d in self._diagnostics() if d.is_error]
        if not diagnostics:
            return {}
        serialized = self._model.serialize()
        line_field: dict[int, str] = {}
        current = ""
        for index, line in enumerate(serialized.splitlines()):
            match = _TOP_LEVEL_KEY_RE.match(line)
            if match and match.group(1) in self._schema:
                current = match.group(1)
            line_field[index] = current
        by_field: dict[str, list[str]] = {}
        for diagnostic in diagnostics:
            field = line_field.get(diagnostic.range.start.line, "")
            if field:
                by_field.setdefault(field, []).append(diagnostic.message)
        return by_field
