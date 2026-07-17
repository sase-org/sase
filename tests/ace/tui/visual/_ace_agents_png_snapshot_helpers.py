"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from xml.etree import ElementTree

from sase.ace.testing import AcePage


def assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = svg.replace("&#160;", " ")
    assert text in svg_plain


def assert_page_svg_styled_text_contains(page: AcePage, text: str) -> None:
    """Assert text across adjacent SVG elements with different Rich styles."""
    svg = page.export_svg(title="ACE visual assertion")
    root = ElementTree.fromstring(svg)
    svg_plain = "".join(
        "".join(element.itertext())
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "text"
    ).replace("\xa0", " ")
    # Rich represents spaces between differently styled SVG runs as x-offsets,
    # not text nodes, so compare the compacted token stream.
    compact_text = text.replace(" ", "")
    assert compact_text in svg_plain, f"styled SVG text did not contain {text!r}"
