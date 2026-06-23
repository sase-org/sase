"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from sase.ace.testing import AcePage

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


def assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = svg.replace("&#160;", " ")
    assert text in svg_plain
