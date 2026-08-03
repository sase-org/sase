"""Unit tests for CLI detail style and prose highlighting."""

from __future__ import annotations

import pytest

from sase.bead.cli_detail_prose import highlight_prose
from sase.bead.cli_detail_style import DetailStyle, resolve_detail_style
from sase.phase_size_presentation import PHASE_SIZE_ACCENTS, PHASE_SIZE_STYLES
from tests.test_bead.cli_show_style_test_helpers import strip_sgr


@pytest.mark.parametrize(
    "color,style,isatty,expected",
    [
        ("never", "auto", False, DetailStyle.PLAIN),
        ("never", "rich", True, DetailStyle.PLAIN),
        ("auto", "auto", False, DetailStyle.PLAIN),
        ("auto", "auto", True, DetailStyle.RICH),
        ("auto", "rich", False, DetailStyle.PLAIN),
        ("auto", "plain", True, DetailStyle.PLAIN),
        ("always", "auto", False, DetailStyle.RICH),
        ("always", "auto", True, DetailStyle.RICH),
        ("always", "plain", False, DetailStyle.PLAIN),
        ("always", "plain", True, DetailStyle.PLAIN),
    ],
)
def test_resolve_detail_style_gate_matrix(
    color: str,
    style: str,
    isatty: bool,
    expected: DetailStyle,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: isatty)

    assert resolve_detail_style(style=style, color=color) is expected


def test_resolve_detail_style_honors_no_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)

    assert resolve_detail_style(style="auto", color="auto") is DetailStyle.PLAIN


def test_resolve_detail_style_rejects_removed_color_style() -> None:
    with pytest.raises(ValueError, match="unknown detail style"):
        resolve_detail_style(style="color", color="always")


def test_highlight_prose_returns_unchanged_for_plain() -> None:
    text = "# Heading\n\nSome text.\n"

    assert highlight_prose(text, style=DetailStyle.PLAIN) == text


def test_highlight_prose_empty_string() -> None:
    assert highlight_prose("", style=DetailStyle.RICH) == ""


def test_highlight_prose_unknown_fence_language_does_not_raise() -> None:
    text = "before\n\n```boguslang123\nsome code\n```\n\nafter\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_unterminated_fence_does_not_raise() -> None:
    text = "before\n\n```python\ndef foo():\n    pass\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_description_with_trailing_whitespace() -> None:
    text = "trailing whitespace here   \nand here\t\n"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_highlight_prose_description_is_only_a_fence() -> None:
    text = "```python\nprint('only a fence')\n```"

    rendered = highlight_prose(text, style=DetailStyle.RICH)

    assert strip_sgr(rendered) == text


def test_phase_size_accents_match_phase_size_styles_hex() -> None:
    for size, accent_hex in PHASE_SIZE_ACCENTS.items():
        assert accent_hex.lower() in PHASE_SIZE_STYLES[size].lower()
