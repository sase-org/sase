"""``%{...}`` alt-shorthand highlighting overlay for ``PromptTextArea``.

Extends the existing overlay approach (rather than adding a separate
highlighter that fights TextArea themes): alt styles are layered onto the
same ``sase-jinja-prompt`` theme used by the Jinja and search overlays, and
alt spans are appended to ``self._highlights`` after the base markdown,
Jinja, and search spans.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from rich.style import Style
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.widgets._jinja_highlight import (
    _JINJA_THEME_NAME,
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.xprompt import alt_inspect

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


class AltSyntaxHighlightMixin(_MixinBase):
    """Overlay ``%{...}`` alt-shorthand spans on top of TextArea highlighting."""

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def on_mount(self) -> None:
        """Register alt styles after the Jinja/search overlay themes exist."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_alt_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_alt_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_alt_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        text = self.text
        if "%{" not in text:
            return
        if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
            return
        if text.count("\n") > _MAX_OVERLAY_LINES:
            return

        for span in alt_inspect.tokenize(text):
            self._append_highlight_span(
                span.start,
                span.end,
                f"alt.{span.kind}",
            )

    def _register_alt_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_alt_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles.update(
            {
                "alt.delimiter": Style(color=app_theme.accent, bold=True),
                "alt.separator": Style(color=app_theme.accent, dim=True),
                "alt.branch_name": Style(color=app_theme.success, bold=True),
                "alt.error": Style(color=app_theme.error, underline=True),
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

    def _resolve_alt_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
