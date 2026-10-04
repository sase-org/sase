"""Flexoki-derived styles for semantic macro highlight roles."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import functools
from types import MappingProxyType
from typing import Literal

from textual.color import Color

from sase.ansi_style import ansi_sgr

from .highlight import HighlightSpan, MacroHighlightRole

ACE_THEME_NAME = "flexoki"
_ARGUMENT_ROLES: frozenset[MacroHighlightRole] = frozenset(
    {
        "macro.arg_delimiter",
        "macro.arg_key",
        "macro.arg_assign",
        "macro.arg_value",
        "macro.arg_value_string",
        "macro.arg_value_number",
        "macro.arg_value_bool",
    }
)
_INVALID_ARGUMENT_VALIDITIES = frozenset(
    {"unknown_key", "type_mismatch", "duplicate_key"}
)
_PROJECT_TAG_ROLES: frozenset[MacroHighlightRole] = frozenset(
    {
        "macro.project_tag.sigil",
        "macro.project_tag.name",
        "macro.project_tag.unknown",
    }
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
    """Return a theme-adaptive sibling color for a macro argument."""
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


def macro_argument_palette(
    family: str | None,
    *,
    foreground: str | None,
    background: str,
    secondary: str | None,
    accent: str | None,
    primary: str | None,
) -> Mapping[MacroHighlightRole, str | None]:
    """Return the theme-derived colors for structured argument roles."""
    return {
        "macro.arg_delimiter": _derive_blended_color(
            family,
            target=background,
            background=background,
            ratio=0.35,
        ),
        "macro.arg_assign": _derive_blended_color(
            family,
            target=background,
            background=background,
            ratio=0.35,
        ),
        "macro.arg_key": derive_argument_color(
            family,
            foreground=foreground,
            background=background,
        ),
        "macro.arg_value": _derive_blended_color(
            family,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "macro.arg_value_string": _derive_blended_color(
            secondary,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "macro.arg_value_number": _derive_blended_color(
            accent,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
        "macro.arg_value_bool": _derive_blended_color(
            primary,
            target=foreground,
            background=background,
            ratio=0.55,
        ),
    }


def _argument_styles(
    colors: Mapping[MacroHighlightRole, str | None],
) -> dict[MacroHighlightRole, HighlightStyle]:
    return {role: HighlightStyle(colors[role]) for role in _ARGUMENT_ROLES}


@functools.cache
def _argument_highlight_theme(
    source: Literal["macro", "directive"],
) -> Mapping[MacroHighlightRole, HighlightStyle]:
    """Return source-specific styles for structured argument roles."""
    from textual.theme import BUILTIN_THEMES

    theme = BUILTIN_THEMES[ACE_THEME_NAME]
    foreground = theme.foreground
    background = theme.background or "#000000"
    family = theme.warning if source == "directive" else theme.success
    return MappingProxyType(
        _argument_styles(
            macro_argument_palette(
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
    styles: Mapping[MacroHighlightRole, HighlightStyle] | None = None,
) -> HighlightStyle:
    """Return the Rich/ANSI style for a concrete semantic highlight span."""
    if span.role in _PROJECT_TAG_ROLES:
        return _project_tag_style_for_span(span)
    if span.source == "directive" and span.role in _ARGUMENT_ROLES:
        style = _argument_highlight_theme("directive")[span.role]
    else:
        style = (styles or highlight_theme())[span.role]
    if span.role in _ARGUMENT_ROLES and span.validity in _INVALID_ARGUMENT_VALIDITIES:
        return replace(style, underline=True)
    return style


def _project_tag_style_for_span(span: HighlightSpan) -> HighlightStyle:
    """Return the D6 chip-matched style for a project-tag span.

    The ``+`` sigil renders dim in the accent and the name bold in the
    accent. Spans without an accent (disabled projects and ``home``)
    render neutral dim. Unknown anchored tags render in the theme
    warning color with an underline.
    """
    neutral, warning = _project_tag_base_colors()
    if span.role == "macro.project_tag.unknown":
        return HighlightStyle(warning, underline=True)
    accent = span.accent
    if accent is None:
        return HighlightStyle(neutral, dim=True)
    if span.role == "macro.project_tag.sigil":
        return HighlightStyle(accent, dim=True)
    return HighlightStyle(accent, bold=True)


@functools.cache
def _project_tag_base_colors() -> tuple[str, str | None]:
    """Return the (neutral, warning) theme colors for project tags."""
    from textual.theme import BUILTIN_THEMES

    theme = BUILTIN_THEMES[ACE_THEME_NAME]
    background = theme.background or "#000000"
    neutral = (
        Color.parse(theme.foreground or "#ffffff")
        .blend(
            Color.parse(background),
            0.35,
        )
        .hex
    )
    return neutral, theme.warning


@functools.cache
def highlight_theme() -> Mapping[MacroHighlightRole, HighlightStyle]:
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
    arg_colors = macro_argument_palette(
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

    styles: dict[MacroHighlightRole, HighlightStyle] = {
        "macro.invocation": HighlightStyle(theme.success, bold=True),
        "macro.invocation_arg": HighlightStyle(invocation_arg),
        "macro.directive": HighlightStyle(theme.warning, bold=True),
        "macro.directive_arg": HighlightStyle(directive_arg),
        **_argument_styles(arg_colors),
        "macro.separator": HighlightStyle(theme.secondary, bold=True, dim=True),
        "macro.skill": HighlightStyle(skill, bold=True),
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
        # Neutral fallbacks so direct theme indexing never fails; the
        # accent-aware path is highlight_style_for_span().
        "macro.project_tag.sigil": HighlightStyle(neutral_code, dim=True),
        "macro.project_tag.name": HighlightStyle(neutral_code, dim=True),
        "macro.project_tag.unknown": HighlightStyle(theme.warning, underline=True),
    }
    return MappingProxyType(styles)


__all__ = [
    "ACE_THEME_NAME",
    "HighlightStyle",
    "derive_argument_color",
    "highlight_style_for_span",
    "highlight_theme",
    "macro_argument_palette",
]
