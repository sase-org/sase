"""Flexoki-derived styles for semantic xprompt highlight roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import functools
from types import MappingProxyType
from typing import Literal

from textual.color import Color

from sase.ansi_style import ansi_sgr

from .highlight import HighlightSpan, XPromptHighlightRole

ACE_THEME_NAME = "flexoki"
_ARGUMENT_ROLES: frozenset[XPromptHighlightRole] = frozenset(
    {
        "xprompt.arg_delimiter",
        "xprompt.arg_key",
        "xprompt.arg_assign",
        "xprompt.arg_value",
        "xprompt.arg_value_string",
        "xprompt.arg_value_number",
        "xprompt.arg_value_bool",
    }
)
_INVALID_ARGUMENT_VALIDITIES = frozenset(
    {"unknown_key", "type_mismatch", "duplicate_key"}
)


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
    return _derive_blended_color(
        base,
        target=foreground,
        background=background,
        ratio=0.40,
    )


def _derive_blended_color(
    base: str | None,
    *,
    target: str | None,
    background: str,
    ratio: float,
) -> str | None:
    """Blend *base* toward an explicit target or readable foreground."""
    if not base:
        return base

    if target:
        target_color = Color.parse(target)
    else:
        background_color = Color.parse(background)
        target_color = (
            Color(255, 255, 255)
            if background_color.brightness < 0.5
            else Color(0, 0, 0)
        )
    return Color.parse(base).blend(target_color, ratio).hex


def xprompt_argument_palette(
    family: str | None,
    *,
    foreground: str | None,
    background: str,
    secondary: str | None,
    accent: str | None,
    primary: str | None,
) -> Mapping[XPromptHighlightRole, str | None]:
    """Return the theme-derived colors for structured argument roles."""
    return {
        "xprompt.arg_delimiter": _derive_blended_color(
            family,
            target=background,
            background=background,
            ratio=0.35,
        ),
        "xprompt.arg_assign": _derive_blended_color(
            family,
            target=background,
            background=background,
            ratio=0.35,
        ),
        "xprompt.arg_key": derive_argument_color(
            family,
            foreground=foreground,
            background=background,
        ),
        "xprompt.arg_value": _derive_blended_color(
            family,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "xprompt.arg_value_string": _derive_blended_color(
            secondary,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "xprompt.arg_value_number": _derive_blended_color(
            accent,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "xprompt.arg_value_bool": _derive_blended_color(
            primary,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
    }


def _argument_styles(
    colors: Mapping[XPromptHighlightRole, str | None],
) -> dict[XPromptHighlightRole, HighlightStyle]:
    return {role: HighlightStyle(colors[role]) for role in _ARGUMENT_ROLES}


@functools.cache
def _argument_highlight_theme(
    source: Literal["xprompt", "directive"],
) -> Mapping[XPromptHighlightRole, HighlightStyle]:
    """Return source-specific styles for structured argument roles."""
    from textual.theme import BUILTIN_THEMES

    theme = BUILTIN_THEMES[ACE_THEME_NAME]
    foreground = theme.foreground
    background = theme.background or "#000000"
    family = theme.warning if source == "directive" else theme.success
    return MappingProxyType(
        _argument_styles(
            xprompt_argument_palette(
                family,
                foreground=foreground,
                background=background,
                secondary=theme.secondary,
                accent=theme.accent,
                primary=theme.primary,
            )
        )
    )


def highlight_style_for_span(
    span: HighlightSpan,
    *,
    styles: Mapping[XPromptHighlightRole, HighlightStyle] | None = None,
) -> HighlightStyle:
    """Return the Rich/ANSI style for a concrete semantic highlight span."""
    if span.source == "directive" and span.role in _ARGUMENT_ROLES:
        style = _argument_highlight_theme("directive")[span.role]
    else:
        style = (styles or highlight_theme())[span.role]
    if span.role in _ARGUMENT_ROLES and span.validity in _INVALID_ARGUMENT_VALIDITIES:
        return replace(style, underline=True)
    return style


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
    arg_colors = xprompt_argument_palette(
        theme.success,
        foreground=foreground,
        background=background,
        secondary=theme.secondary,
        accent=theme.accent,
        primary=theme.primary,
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
        **_argument_styles(arg_colors),
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
    "highlight_style_for_span",
    "highlight_theme",
    "xprompt_argument_palette",
]
