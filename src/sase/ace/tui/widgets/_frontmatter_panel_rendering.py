"""Rendering, navigation rows, and diagnostics for ``FrontmatterPanel``."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from rich.text import Text

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

_SUBTITLE_POPULATED = "a add · e edit · d delete · R raw · h/l fold · esc done"
_SUBTITLE_EMPTY = "a add · R raw · esc done"
_SUBTITLE_EDIT = "enter save · esc cancel"
_SUBTITLE_RAW = "esc apply · live-validated"


class FrontmatterPanelRenderingMixin(_MixinBase):
    """Rows view rendering and diagnostic attribution for the panel."""

    if TYPE_CHECKING:
        _adding_field: str | None
        _content_lines: int
        _edit_mode: str
        _fields: list[str]
        _folded: set[str]
        _model: PromptFrontmatter
        _schema: dict[str, Any]
        _selected: int

        def _editable_text(self, field: str) -> str: ...
        def _selected_nav(self) -> tuple[str, str] | None: ...

    def _refresh(self) -> None:
        """Rebuild the rows renderable, status chip, and subtitle."""
        from textual.widgets import Static

        rows = self.query_one("#frontmatter-rows", Static)
        renderable, line_count = self._build_rows()
        rows.update(renderable)
        self._content_lines = line_count
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
        elif self._edit_mode == "raw":
            self.border_subtitle = _SUBTITLE_RAW
        elif self._model.is_empty:
            self.border_subtitle = _SUBTITLE_EMPTY
        else:
            self.border_subtitle = _SUBTITLE_POPULATED

    def _build_rows(self) -> tuple[Text, int]:
        """Return the rows renderable and its rendered line count."""
        if self._model.is_empty and self._adding_field is None:
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
            if field == "input":
                rows.extend(("input", arg.name) for arg in self._model.inputs)
            elif field == "xprompts":
                rows.extend(("xprompt", name) for name in self._model.xprompts)
        return rows

    @staticmethod
    def _empty_state() -> Text:
        """The just-triggered empty panel guidance."""
        text = Text()
        text.append("No properties yet.\n", style="dim")
        text.append("Press ", style="dim")
        text.append("a", style="bold #87D7FF")
        text.append(" to add:  ", style="dim")
        text.append(
            "name · description · tags · input · xprompts · skill · snippet",
            style="dim",
        )
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
        if structured:
            folded = field in self._folded
            row.append("▸ " if folded else "▾ ", style="cyan")
            count = (
                len(self._model.inputs)
                if field == "input"
                else len(self._model.xprompts)
            )
            label = "item" if count == 1 else "items"
            row.append(f"{count} {label}", style="dim")
            rows = [row]
            if not folded:
                rows.extend(self._render_sub_items(field, selected=selected))
            return rows
        row.append(self._value_summary(field))
        return [row]

    def _render_sub_items(
        self, field: str, *, selected: tuple[str, str] | None
    ) -> list[Text]:
        """Render the sub-item lines for ``input`` / ``xprompts``."""
        lines: list[Text] = []
        if field == "input":
            for arg in self._model.inputs:
                lines.append(
                    self._input_item_line(arg, selected=selected == ("input", arg.name))
                )
        else:
            for name, xprompt in self._model.xprompts.items():
                lines.append(
                    self._xprompt_item_line(
                        name, xprompt, selected=selected == ("xprompt", name)
                    )
                )
        if not lines:
            empty = Text("    • ")
            empty.append("(none)", style="dim italic")
            lines.append(empty)
        return lines

    @staticmethod
    def _input_item_line(arg: InputArg, *, selected: bool = False) -> Text:
        """One ``input`` sub-item: name, type, required/default, description."""
        line = Text("    • ")
        line.append(arg.name, style="reverse #87D7FF" if selected else "#87D7FF")
        line.append(f"  {arg.type.value}", style="green")
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
