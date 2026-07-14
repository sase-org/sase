"""Transient yank highlight overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from rich.style import Style
from textual.timer import Timer
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


_YANK_FLASH_SECONDS = 0.2


class YankHighlightMixin(_MixinBase):
    """Briefly flash the exact region copied by a vim yank."""

    if TYPE_CHECKING:

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._yank_flash_span: tuple[int, int] | None = None
        self._yank_flash_generation = 0
        self._yank_flash_timer: Timer | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        """Register the yank style after the other overlay themes exist."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_yank_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_yank_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_yank_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _flash_yank(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> None:
        """Show a fresh yank flash and restart its expiry window."""
        start_offset = self._absolute_offset(start)
        end_offset = self._absolute_offset(end)
        if end_offset <= start_offset:
            return

        self._yank_flash_span = (start_offset, end_offset)
        self._yank_flash_generation += 1
        generation = self._yank_flash_generation
        if self._yank_flash_timer is not None:
            self._yank_flash_timer.stop()
        self._refresh_yank_overlay()
        self._yank_flash_timer = self.set_timer(
            _YANK_FLASH_SECONDS,
            lambda: self._clear_yank_flash(generation),
        )

    def _clear_yank_flash(self, generation: int) -> None:
        """Clear the current flash unless this is a stale timer callback."""
        if generation != self._yank_flash_generation:
            return
        self._yank_flash_span = None
        self._yank_flash_timer = None
        if self.is_mounted:
            self._refresh_yank_overlay()

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        span = self._yank_flash_span
        if span is None:
            return

        text = self.text
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        self._append_highlight_span(*span, "yank.flash")

    def _refresh_yank_overlay(self) -> None:
        self._build_highlight_map()
        self.refresh()

    def _register_yank_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_yank_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles["yank.flash"] = Style(
            color=app_theme.foreground,
            bgcolor=app_theme.success,
            bold=True,
        )
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_yank_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
