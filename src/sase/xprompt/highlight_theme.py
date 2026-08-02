"""Flexoki-derived styles for semantic xprompt highlight roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import functools
from types import MappingProxyType

from textual.color import Color

from sase.ansi_style import ansi_sgr

from .highlight import XPromptHighlightRole

ACE_THEME_NAME = "flexoki"


@dataclass(frozen=True, slots=True)
class HighlightStyle:
    """A frontend-neutral foreground style with Rich and ANSI projections."""

    color: str | None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False

    @property
    def rich_style(self) -> str:
        parts = [
            name
            for name, enabled in (
                ("bold", self.bold),
                ("dim", self.dim),
                ("italic", self.italic),
                ("underline", self.underline),
            )
            if enabled
        ]
        if self.color is not None:
            parts.append(self.color)
        return " ".join(parts)

    @property
    def ansi_sgr(self) -> str:
        return ansi_sgr(
            color=self.color,
            bold=self.bold,
            dim=self.dim,
            italic=self.italic,
            underline=self.underline,
        )


def derive_argument_color(
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


@functools.cache
def highlight_theme() -> Mapping[XPromptHighlightRole, HighlightStyle]:
    """Return the complete semantic palette derived from ACE's pinned theme."""
    from textual.theme import BUILTIN_THEMES

    theme = BUILTIN_THEMES[ACE_THEME_NAME]
    foreground = theme.foreground
    background = theme.background or "#000000"
    invocation_arg = derive_argument_color(
        theme.success,
        foreground=foreground,
        background=background,
    )
    directive_arg = derive_argument_color(
        theme.warning,
        foreground=foreground,
        background=background,
    )
    skill = derive_argument_color(
        theme.accent,
        foreground=foreground,
        background=background,
    )
    neutral_code = (
        Color.parse(foreground or "#ffffff")
        .blend(
            Color.parse(background),
            0.35,
        )
        .hex
    )

    styles: dict[XPromptHighlightRole, HighlightStyle] = {
        "xprompt.invocation": HighlightStyle(theme.success, bold=True),
        "xprompt.invocation_arg": HighlightStyle(invocation_arg),
        "xprompt.directive": HighlightStyle(theme.warning, bold=True),
        "xprompt.directive_arg": HighlightStyle(directive_arg),
        "xprompt.separator": HighlightStyle(theme.secondary, bold=True, dim=True),
        "xprompt.skill": HighlightStyle(skill, bold=True),
        "jinja.delimiter": HighlightStyle(theme.accent, dim=True),
        "jinja.statement": HighlightStyle(theme.accent, bold=True),
        "jinja.variable": HighlightStyle(theme.secondary, bold=True),
        "jinja.comment": HighlightStyle(foreground, dim=True, italic=True),
        "jinja.filter": HighlightStyle(theme.success),
        "jinja.keyword": HighlightStyle(theme.accent, bold=True),
        "jinja.operator": HighlightStyle(foreground, dim=True),
        "alt.delimiter": HighlightStyle(theme.accent, bold=True),
        "alt.separator": HighlightStyle(theme.accent, dim=True),
        "alt.branch_name": HighlightStyle(theme.success, bold=True),
        "alt.error": HighlightStyle(theme.error, underline=True),
        "placeholder": HighlightStyle(theme.secondary, bold=True),
        "artifact_ref": HighlightStyle(invocation_arg),
        "code.fence": HighlightStyle(neutral_code),
        "code.inline": HighlightStyle(neutral_code),
    }
    return MappingProxyType(styles)


__all__ = [
    "ACE_THEME_NAME",
    "HighlightStyle",
    "derive_argument_color",
    "highlight_theme",
]
