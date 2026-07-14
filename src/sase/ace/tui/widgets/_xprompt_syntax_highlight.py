"""Xprompt syntax highlighting overlay for ``PromptTextArea``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from rich.style import Style
from textual.color import Color
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt import xprompt_inspect

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.xprompt.xprompt_inspect import XPromptSpan
else:
    _MixinBase = object


def _derive_argument_color(
    base: str | None,
    *,
    foreground: str | None,
    background: str,
) -> str | None:
    """Return a theme-adaptive sibling color for an xprompt argument."""
    if not base:
        return base

    if foreground:
        target = Color.parse(foreground)
    else:
        background_color = Color.parse(background)
        target = (
            Color(255, 255, 255)
            if background_color.brightness < 0.5
            else Color(0, 0, 0)
        )
    return Color.parse(base).blend(target, 0.40).hex


class XPromptSyntaxHighlightMixin(_MixinBase):
    """Overlay recognized xprompt syntax on TextArea markdown highlighting."""

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def on_mount(self) -> None:
        """Register xprompt styles after the base Jinja theme exists."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_xprompt_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_xprompt_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_xprompt_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if "#" not in text and "%" not in text and "---" not in text:
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        try:
            spans: list[XPromptSpan] = xprompt_inspect.tokenize(text)
        except Exception:
            return
        for span in spans:
            self._append_highlight_span(
                span.start,
                span.end,
                f"xprompt.{span.kind}",
            )

    def _register_xprompt_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_xprompt_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        background = app_theme.background or "#000000"
        syntax_styles.update(
            {
                "xprompt.invocation": Style(
                    color=app_theme.success,
                    bold=True,
                ),
                "xprompt.invocation_arg": Style(
                    color=_derive_argument_color(
                        app_theme.success,
                        foreground=app_theme.foreground,
                        background=background,
                    )
                ),
                "xprompt.directive": Style(
                    color=app_theme.warning,
                    bold=True,
                ),
                "xprompt.directive_arg": Style(
                    color=_derive_argument_color(
                        app_theme.warning,
                        foreground=app_theme.foreground,
                        background=background,
                    )
                ),
                "xprompt.separator": Style(
                    color=app_theme.secondary,
                    dim=True,
                    bold=True,
                ),
            }
        )
        theme = dataclasses.replace(
            base,
            name=active_name,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        if apply:
            self._set_theme(theme.name)

    def _resolve_xprompt_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
