"""Line rendering mixin for PromptTextArea."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.worker import Worker

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class LineRenderingMixin(_MixinBase):
    """Mixin providing custom line rendering for vim mode indicators.

    Mixed into :class:`~sase.ace.tui.widgets.prompt_text_area.PromptTextArea`.
    """

    _VIM_MODE_CLASSES: ClassVar[dict[str, str]] = {
        "insert": "-vim-insert",
        "normal": "-vim-normal",
        "visual": "-vim-visual",
        "visual_line": "-vim-visual",
    }
    _VIM_CURSOR_CLASSES: ClassVar[tuple[str, ...]] = (
        "-vim-insert",
        "-vim-normal",
        "-vim-visual",
    )

    if TYPE_CHECKING:
        _vim_mode: str

    def on_mount(self) -> None:
        """Dispatch the cooperative mount hook exactly once.

        Textual already invokes every ``on_mount`` along the MRO, so the
        prompt mixins keep their mount bodies in :meth:`_prompt_mount_hook`
        (a non-dispatched name) and chain cooperatively there. This single
        handler fans out to the most-derived hook, which runs each body once,
        base-first. It never chains into ``ScrollView.on_mount``; Textual
        dispatches that itself.
        """
        self._prompt_mount_hook()

    def _prompt_mount_hook(self) -> None:
        """Terminate the mount-hook chain with the cursor-class seed."""
        self._sync_vim_cursor_class()

    def on_unmount(self) -> None:
        """Dispatch the cooperative unmount hook exactly once."""
        self._prompt_unmount_hook()

    def _prompt_unmount_hook(self) -> None:
        """Terminate the unmount-hook chain; there is no base body."""

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Dispatch the cooperative worker hook exactly once."""
        self._prompt_worker_hook(event)

    def _prompt_worker_hook(self, event: Worker.StateChanged) -> None:
        """Terminate the worker-hook chain; unknown groups are ignored."""
        del event

    def _sync_vim_cursor_class(self) -> None:
        """Sync the CSS class that colors Textual's native cursor cell."""
        active_class = self._VIM_MODE_CLASSES.get(self._vim_mode, "-vim-insert")
        for class_name in self._VIM_CURSOR_CLASSES:
            self.set_class(class_name == active_class, class_name)

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
