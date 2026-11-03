"""Decoded SVG text matching treats wrap and styled gaps as visible text."""

from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    decoded_svg_text_contains,
)


def test_decoded_svg_text_contains_literal_and_wrapped() -> None:
    needle = "the archived prompt reads back verbatim"
    assert decoded_svg_text_contains(needle, needle)
    wrapped = "the archived prompt reads back\nverbatim"
    assert decoded_svg_text_contains(wrapped, needle)
    styled = "thearchivedpromptreadsbackverbatim"
    assert decoded_svg_text_contains(styled, needle)
    interleaved = "▎ the archived prompt reads back │ │ │ │ ▎ verbatim"
    assert decoded_svg_text_contains(interleaved, needle)
    assert not decoded_svg_text_contains("ARCHIVED\nread-only", needle)
