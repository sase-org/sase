from __future__ import annotations

from typing import get_args

from sase.xprompt.highlight import HighlightSpan, XPromptHighlightRole
from sase.xprompt.highlight_theme import (
    HighlightStyle,
    derive_argument_color,
    highlight_style_for_span,
    highlight_theme,
)


def test_flexoki_role_palette_is_complete_and_stable() -> None:
    styles = highlight_theme()

    assert set(styles) == set(get_args(XPromptHighlightRole))
    assert styles == {
        "xprompt.invocation": HighlightStyle("#66800B", bold=True),
        "xprompt.invocation_arg": HighlightStyle("#A3B166"),
        "xprompt.directive": HighlightStyle("#AD8301", bold=True),
        "xprompt.directive_arg": HighlightStyle("#CDB360"),
        "xprompt.arg_delimiter": HighlightStyle("#47580C"),
        "xprompt.arg_key": HighlightStyle("#A3B166"),
        "xprompt.arg_assign": HighlightStyle("#47580C"),
        "xprompt.arg_value": HighlightStyle("#BAC488"),
        "xprompt.arg_value_string": HighlightStyle("#9CC5BB"),
        "xprompt.arg_value_number": HighlightStyle("#D2BFDE"),
        "xprompt.arg_value_bool": HighlightStyle("#9AB4CE"),
        "xprompt.separator": HighlightStyle("#24837B", bold=True, dim=True),
        "xprompt.skill": HighlightStyle("#C3ABD8", bold=True),
        "jinja.delimiter": HighlightStyle("#9B76C8", dim=True),
        "jinja.statement": HighlightStyle("#9B76C8", bold=True),
        "jinja.variable": HighlightStyle("#24837B", bold=True),
        "jinja.comment": HighlightStyle("#FFFCF0", dim=True, italic=True),
        "jinja.filter": HighlightStyle("#66800B"),
        "jinja.keyword": HighlightStyle("#9B76C8", bold=True),
        "jinja.operator": HighlightStyle("#FFFCF0", dim=True),
        "alt.delimiter": HighlightStyle("#9B76C8", bold=True),
        "alt.separator": HighlightStyle("#9B76C8", dim=True),
        "alt.branch_name": HighlightStyle("#66800B", bold=True),
        "alt.error": HighlightStyle("#AF3029", underline=True),
        "placeholder": HighlightStyle("#24837B", bold=True),
        "artifact_ref": HighlightStyle("#A3B166"),
        "code.fence": HighlightStyle("#ABA9A1"),
        "code.inline": HighlightStyle("#ABA9A1"),
    }


def test_style_projections_include_attributes_and_color() -> None:
    style = HighlightStyle(
        "#66800B",
        bold=True,
        dim=True,
        italic=True,
        underline=True,
    )

    assert style.rich_style == "bold dim italic underline #66800B"
    assert style.ansi_sgr == "\x1b[1;2;3;4;38;5;64m"


def test_empty_style_projections_are_empty() -> None:
    style = HighlightStyle(None)

    assert style.rich_style == ""
    assert style.ansi_sgr == ""


def test_derive_argument_color_retains_tui_values() -> None:
    assert (
        derive_argument_color(
            "#66800B",
            foreground="#FFFCF0",
            background="#100F0F",
        )
        == "#A3B166"
    )
    assert (
        derive_argument_color(
            "#66800B",
            foreground=None,
            background="#FFFCF0",
        )
        == "#3D4C06"
    )
    assert derive_argument_color(None, foreground="#fff", background="#000") is None


def test_directive_argument_style_uses_warning_family() -> None:
    style = highlight_style_for_span(
        HighlightSpan(
            0,
            3,
            "xprompt.arg_key",
            source="directive",
        )
    )

    assert style == HighlightStyle("#CDB360")
    assert style != highlight_theme()["xprompt.arg_key"]


def test_invalid_argument_style_preserves_foreground_and_underlines() -> None:
    style = highlight_style_for_span(
        HighlightSpan(
            0,
            3,
            "xprompt.arg_key",
            validity="unknown_key",
            source="directive",
        )
    )

    assert style == HighlightStyle("#CDB360", underline=True)
