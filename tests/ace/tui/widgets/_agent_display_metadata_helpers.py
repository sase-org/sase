"""Shared assertions for agent display metadata tests."""

from __future__ import annotations

from rich.text import Text

MAJOR_SECTION_RULE = "\u2500" * 50


def assert_metadata_prefix(text: Text, *expected_lines: str) -> None:
    assert text.plain.splitlines()[: len(expected_lines)] == list(expected_lines)


def assert_span_covers(text: Text, needle: str, style: str) -> None:
    plain = text.plain
    start = plain.index(needle)
    end = start + len(needle)
    assert any(
        span.start <= start and span.end >= end and str(span.style) == style
        for span in text.spans
    )


def assert_dim_divider_before(text: Text, section: str) -> None:
    plain = text.plain
    section_start = plain.index(section)
    rule_start = plain.rfind(MAJOR_SECTION_RULE, 0, section_start)
    assert rule_start != -1
    assert plain[rule_start - 1 : section_start] == (f"\n{MAJOR_SECTION_RULE}\n\n")
    rule_end = rule_start + len(MAJOR_SECTION_RULE)
    assert any(
        span.start <= rule_start and span.end >= rule_end and str(span.style) == "dim"
        for span in text.spans
    )
