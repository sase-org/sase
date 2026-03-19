"""Line rendering mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class LineRenderingMixin(_MixinBase):
    """Mixin providing custom line rendering for vim mode indicators.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    if TYPE_CHECKING:
        _vim_mode: str

    def render_line(self, y: int) -> Strip:
        """Bypass cache in NORMAL mode so relative line numbers stay current."""
        if self._vim_mode == "normal" and self.show_line_numbers:
            return self._render_line(y)
        if self._vim_mode != "normal" and self.show_line_numbers:
            return self._render_insert_line(y)
        return super().render_line(y)

    def _render_insert_line(self, y: int) -> Strip:
        """Color absolute line numbers in INSERT mode with cyan (#3AA99F)."""
        strip = super().render_line(y)
        if not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        _line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        gutter_style = (self._theme.gutter_style or Style.null()) + Style(
            color="#3AA99F"
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = Segment(segments[0].text, gutter_style)
            return Strip(segments, strip.cell_length)

        return strip

    def _render_line(self, y: int) -> Strip:
        """Show relative line numbers in NORMAL mode."""
        strip = super()._render_line(y)
        if self._vim_mode != "normal" or not self.show_line_numbers:
            return strip

        _scroll_x, scroll_y = self.scroll_offset
        y_offset = y + scroll_y

        if y_offset >= self.wrapped_document.height:
            return strip

        try:
            line_info = self.wrapped_document._offset_to_line_info[y_offset]
        except IndexError:
            return strip

        if line_info is None:
            return strip

        line_index, section_offset = line_info
        if section_offset != 0:
            return strip

        cursor_row = self.cursor_location[0]
        if line_index == cursor_row:
            gutter_content = str(line_index + 1)
        else:
            gutter_content = str(abs(line_index - cursor_row))

        gutter_width = self.gutter_width
        gutter_width_no_margin = gutter_width - 2

        theme = self._theme
        if line_index == cursor_row:
            base = (
                (theme.cursor_line_gutter_style or Style.null())
                if self.highlight_cursor_line
                else Style.null()
            )
            gutter_style = base + Style(color="#D0A215", bold=True)
        elif line_index < cursor_row:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#4385BE")
        else:
            gutter_style = (theme.gutter_style or Style.null()) + Style(color="#8B7EC8")

        new_gutter = Segment(
            f"{gutter_content:>{gutter_width_no_margin}}  ", gutter_style
        )
        segments = list(strip._segments)
        if segments:
            segments[0] = new_gutter
            return Strip(segments, strip.cell_length)

        return strip
