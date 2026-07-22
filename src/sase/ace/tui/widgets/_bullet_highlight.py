"""Leading bullet-dash highlighting overlay for ``PromptTextArea``.

Extends the shared overlay approach used by the Jinja/alt/xprompt highlighters:
the bullet color is layered onto the same ``sase-jinja-prompt`` theme, and the
dash spans are appended to ``self._highlights`` after the base markdown and
code-block spans so a list marker stays visible even inside a fenced block.

Only the ``-`` of a ``- `` bullet is colored -- a dash that opens a line with
nothing but spaces to its left and a space to its right. That single, common
structural glyph gets the theme's primary hue (unused by every other prompt
overlay) lifted toward the foreground so it pops against the editor canvas.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

from rich.style import Style
from textual.color import Color
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


# A leading bullet: start of line, only spaces before the dash, a space after.
# The lookahead keeps the space out of the span so only the ``-`` is colored.
_BULLET_DASH_RE = re.compile(r"(?m)^ *(-)(?= )")

# How far to nudge the primary hue toward the foreground. Lifting toward the
# text color raises contrast against the *background* in both dark and light
# themes while preserving the primary hue's identity.
_BULLET_DASH_FOREGROUND_LIFT = 0.30

# Fallback blue if a theme somehow leaves ``primary`` unset (flexoki primary).
_BULLET_DASH_FALLBACK_PRIMARY = "#205EA6"


def _bullet_dash_spans(text: str) -> tuple[tuple[int, int], ...]:
    """Return character offsets of leading ``- `` bullet dashes in *text*.

    Offsets are Python character offsets. ``PromptTextArea`` converts them to
    Textual's UTF-8 byte columns through its shared overlay span helper.
    """
    if "- " not in text:
        return ()
    if len(text) > _MAX_OVERLAY_BYTES:
        return ()
    if len(text.encode("utf-8")) > _MAX_OVERLAY_BYTES:
        return ()
    if text.count("\n") > _MAX_OVERLAY_LINES:
        return ()
    return _scan_bullet_dash_spans(text)


def _scan_bullet_dash_spans(text: str) -> tuple[tuple[int, int], ...]:
    return tuple(
        (match.start(1), match.end(1)) for match in _BULLET_DASH_RE.finditer(text)
    )


def _bullet_dash_color(primary: str | None, foreground: str | None) -> Color:
    """Return a theme-adaptive, high-contrast color for leading bullet dashes.

    Nudges the theme's primary color toward the foreground so the dash lifts
    off the editor background and stays easy to spot, while keeping the primary
    hue that no other prompt overlay uses.
    """
    base = Color.parse(primary or _BULLET_DASH_FALLBACK_PRIMARY)
    if foreground is None:
        return base
    return base.blend(Color.parse(foreground), _BULLET_DASH_FOREGROUND_LIFT)


class BulletHighlightMixin(_MixinBase):
    """Overlay leading bullet-dash spans on top of TextArea highlighting."""

    if TYPE_CHECKING:

        def _append_highlight_span(
            self,
            start: int,
            end: int,
            style_name: str,
        ) -> None: ...

    def on_mount(self) -> None:
        """Register the bullet style after the base overlay themes exist."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_bullet_text_area_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_bullet_text_area_theme()

    def _register_jinja_text_area_theme(self) -> None:
        register_jinja = getattr(super(), "_register_jinja_text_area_theme", None)
        if callable(register_jinja):
            register_jinja()
        self._register_bullet_text_area_theme(_JINJA_THEME_NAME, apply=False)

    def _build_highlight_map(self) -> None:
        super()._build_highlight_map()
        for start, end in _bullet_dash_spans(self.text):
            self._append_highlight_span(start, end, "bullet.dash")

    def _register_bullet_text_area_theme(
        self,
        theme_name: str | None = None,
        *,
        apply: bool = True,
    ) -> None:
        active_name = theme_name or str(getattr(self, "theme", "css") or "css")
        base = self._resolve_bullet_base_theme(active_name)
        syntax_styles = dict(base.syntax_styles)
        app_theme = self.app.current_theme
        syntax_styles.update(
            {
                "bullet.dash": Style(
                    color=_bullet_dash_color(
                        app_theme.primary,
                        app_theme.foreground,
                    ).hex,
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

    def _resolve_bullet_base_theme(self, theme_name: str) -> TextAreaTheme:
        try:
            theme: TextAreaTheme | None = self._themes[theme_name]
        except KeyError:
            theme = TextAreaTheme.get_builtin_theme(theme_name)
        if theme is None:
            fallback = TextAreaTheme.get_builtin_theme("css")
            assert fallback is not None
            return fallback
        return theme
