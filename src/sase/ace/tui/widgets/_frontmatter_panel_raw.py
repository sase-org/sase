"""Raw YAML editing mode for ``FrontmatterPanel``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static, TextArea
import yaml  # type: ignore[import-untyped]

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.frontmatter_schema import FrontmatterDiagnostic, validate_frontmatter
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FrontmatterPanelRawMixin(_MixinBase):
    """Raw YAML escape hatch with debounced, line-anchored diagnostics."""

    if TYPE_CHECKING:
        _adding_field: str | None
        _edit_mode: str
        _feedback: str
        _feedback_lines: int
        _fields: list[str]
        _model: PromptFrontmatter
        _raw_diagnostics_generation: int
        _selected: int

        def _emit_changed(self) -> None: ...
        def _push_undo(self) -> None: ...
        def _refresh(self) -> None: ...
        def _refresh_chrome(self) -> None: ...
        def _set_feedback_lines(self, text: str, feedback: Static) -> bool: ...
        def _show_rows_only(self) -> None: ...
        def _update_raw_content_lines(self, editor: VimTextArea) -> None: ...

    def _begin_raw(self) -> None:
        self._edit_mode = "raw"
        self._adding_field = None
        editor = self.query_one("#frontmatter-raw", VimTextArea)
        # If comments were detected, show exactly what was loaded so the user
        # can see the syntax canonical serialization would discard.
        editor.text = (
            self._model.original_text
            if self._model.has_comments and self._model.original_text
            else self._model.serialize()
        )
        self._update_raw_content_lines(editor)
        self.query_one("#frontmatter-rows", Static).add_class("hidden")
        self.query_one("#frontmatter-inline", SingleLineVimTextArea).add_class("hidden")
        self.query_one("#frontmatter-content", VimTextArea).add_class("hidden")
        editor.remove_class("hidden")
        self._refresh_chrome()
        self._schedule_layout_update()  # type: ignore[attr-defined]
        self.call_after_refresh(lambda: self._update_raw_content_lines(editor))
        editor.focus()
        editor._update_vim_mode_display()
        self._schedule_raw_validation(editor.text)

    def _commit_raw(self) -> None:
        editor = self.query_one("#frontmatter-raw", VimTextArea)
        text = editor.text
        try:
            _validate_yaml_shape(text)
            model = PromptFrontmatter.parse(text)
        except Exception as exc:
            self._render_raw_diagnostics([], parse_error=str(exc))
            return
        self._push_undo()
        self._model = model
        self._fields = self._model.present_fields()
        self._selected = min(self._selected, max(0, len(self._fields) - 1))
        self._show_rows_only()
        self._edit_mode = "rows"
        self._refresh()
        self.focus()
        self._schedule_layout_update()  # type: ignore[attr-defined]
        self._emit_changed()

    def _discard_raw(self) -> None:
        """Exit raw mode without applying even an unparseable buffer."""
        self._show_rows_only()
        self._edit_mode = "rows"
        self._feedback = "Discarded raw edits"
        feedback = self.query_one("#frontmatter-feedback", Static)
        feedback.update("")
        feedback.add_class("hidden")
        self._refresh()
        self.focus()
        self._schedule_layout_update()  # type: ignore[attr-defined]

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id in {"frontmatter-inline", "frontmatter-content"}:
            event.stop()
            if event.text_area.id == "frontmatter-inline":
                if self._edit_mode == "picker":
                    self._update_picker(event.text_area.text)  # type: ignore[attr-defined]
                elif self._edit_mode == "cell":
                    self._refresh_cell_feedback()  # type: ignore[attr-defined]
                    self._refresh()  # type: ignore[attr-defined]
            return
        if event.text_area.id != "frontmatter-raw":
            return
        event.stop()
        if self._edit_mode == "raw":
            if isinstance(event.text_area, VimTextArea):
                self._update_raw_content_lines(event.text_area)
            self._schedule_raw_validation(event.text_area.text)

    def _schedule_raw_validation(self, text: str) -> None:
        self._raw_diagnostics_generation += 1
        generation = self._raw_diagnostics_generation

        def _validate() -> None:
            if (
                generation != self._raw_diagnostics_generation
                or self._edit_mode != "raw"
            ):
                return
            try:
                diagnostics = validate_frontmatter(text) if text.strip() else []
            except Exception:
                diagnostics = []
            self._render_raw_diagnostics(diagnostics)

        self.set_timer(0.15, _validate)

    def _render_raw_diagnostics(
        self,
        diagnostics: list[FrontmatterDiagnostic],
        *,
        parse_error: str = "",
    ) -> None:
        errors = [diagnostic for diagnostic in diagnostics if diagnostic.is_error]
        if parse_error:
            errors = []
        if not self.query_one("#frontmatter-raw", VimTextArea).text.strip():
            chip = "[dim]⟨ ⟩[/]"
        elif errors or parse_error:
            count = len(errors) or 1
            chip = f"[bold red]⟨! {count}⟩[/]"
        else:
            chip = "[bold green]⟨✓⟩[/]"
        self.border_title = f"frontmatter (raw)  {chip}"

        feedback = self.query_one("#frontmatter-feedback", Static)
        lines = Text()
        if parse_error:
            lines.append(f"YAML: {parse_error}", style="red")
        else:
            for index, diagnostic in enumerate(errors[:4]):
                if index:
                    lines.append("\n")
                lines.append(
                    f"line {diagnostic.range.start.line + 1}: {diagnostic.message}",
                    style="red",
                )
        feedback.update(lines)
        if lines.plain:
            feedback.remove_class("hidden")
        else:
            feedback.add_class("hidden")
        if self._set_feedback_lines(lines.plain, feedback):
            self._schedule_layout_update()  # type: ignore[attr-defined]


def _validate_yaml_shape(text: str) -> None:
    """Raise a concise error for unparseable/non-mapping raw YAML."""
    stripped = text.strip()
    if not stripped:
        return
    if stripped.startswith("---"):
        lines = stripped.splitlines()
        if len(lines) < 2 or lines[-1].strip() != "---":
            raise ValueError("frontmatter needs a closing --- delimiter")
        stripped = "\n".join(lines[1:-1])
    try:
        value = yaml.safe_load(stripped)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        message = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        if mark is not None:
            raise ValueError(f"line {mark.line + 1}: {message}") from None
        raise ValueError(message) from None
    if value is not None and not isinstance(value, dict):
        raise ValueError("frontmatter must be a YAML mapping")
