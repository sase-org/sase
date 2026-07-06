"""Raw YAML editing mode for ``FrontmatterPanel``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static, TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.frontmatter_schema import validate_frontmatter
from sase.xprompt.prompt_frontmatter import PromptFrontmatter

if TYPE_CHECKING:
    from textual.containers import Vertical as _MixinBase
else:
    _MixinBase = object


class FrontmatterPanelRawMixin(_MixinBase):
    """Raw YAML escape hatch and live validation chip behavior."""

    if TYPE_CHECKING:
        _adding_field: str | None
        _edit_mode: str
        _fields: list[str]
        _model: PromptFrontmatter
        _selected: int

        def _emit_changed(self) -> None: ...
        def _refresh(self) -> None: ...
        def _refresh_chrome(self) -> None: ...
        def _show_rows_only(self) -> None: ...

    def _begin_raw(self) -> None:
        """Enter raw-YAML mode: edit the canonical serialized frontmatter."""
        self._edit_mode = "raw"
        self._adding_field = None
        editor = self.query_one("#frontmatter-raw", VimTextArea)
        editor.text = self._model.serialize()
        rows = self.query_one("#frontmatter-rows", Static)
        rows.add_class("hidden")
        self.query_one("#frontmatter-inline", SingleLineVimTextArea).add_class("hidden")
        editor.remove_class("hidden")
        self._refresh_chrome()
        editor.focus()
        editor._update_vim_mode_display()
        self._update_raw_chip(editor.text)

    def _commit_raw(self) -> None:
        """Re-parse the raw YAML into the model and return to the rows view.

        Unparseable structure (e.g. a non-underscore local xprompt name) keeps
        the user in raw mode with the core message rather than dropping data.
        """
        editor = self.query_one("#frontmatter-raw", VimTextArea)
        text = editor.text
        try:
            model = PromptFrontmatter.parse(text)
        except Exception as exc:  # surface, do not silently discard
            self.border_subtitle = f"⚠ {exc}"
            return
        self._model = model
        self._fields = self._model.present_fields()
        self._selected = min(self._selected, max(0, len(self._fields) - 1))
        self._show_rows_only()
        self._edit_mode = "rows"
        self._refresh()
        self.focus()
        self._emit_changed()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Live-validate raw edits and keep child-editor changes off the bar."""
        if event.text_area.id == "frontmatter-inline":
            event.stop()
            return
        if event.text_area.id != "frontmatter-raw":
            return
        event.stop()
        if self._edit_mode == "raw":
            self._update_raw_chip(event.text_area.text)

    def _update_raw_chip(self, text: str) -> None:
        """Refresh the status chip from a live ``validate_frontmatter`` pass."""
        try:
            diagnostics = validate_frontmatter(text) if text.strip() else []
        except Exception:
            diagnostics = []
        errors = sum(1 for d in diagnostics if d.is_error)
        if not text.strip():
            chip = "[dim]⟨ ⟩[/]"
        elif errors:
            chip = f"[bold red]⟨! {errors}⟩[/]"
        else:
            chip = "[bold green]⟨✓⟩[/]"
        self.border_title = f"frontmatter (raw)  {chip}"
