"""Shared assertions for agent display metadata tests."""

from __future__ import annotations

from io import StringIO
from typing import Any

from rich.console import Console
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


def assert_kind_header(
    text: Text,
    label: str,
    color: str,
    *,
    before: str | None = None,
) -> None:
    """Assert a kind chrome line at the top of a metadata document."""
    assert text.plain.startswith(f"{label}\n")
    assert_span_covers(text, label, f"bold {color} underline")
    if before is None:
        return
    start = text.plain.index(label)
    limit = text.plain.index(before)
    covering = [
        span
        for span in text.spans
        if span.start <= start < span.end
        and str(span.style) == f"bold {color} underline"
    ]
    assert covering
    assert covering[0].end <= limit


def _logical_plain(renderable: Any) -> str:
    """Return logical plain text for Text, Group, card containers, or caches."""
    from rich.console import Group

    from sase.ace.tui.widgets.decks.card_block import is_card_container

    if isinstance(renderable, Text):
        return renderable.plain
    if is_card_container(renderable):
        return "\n".join(
            _logical_plain(child) for child in getattr(renderable, "renderables", ())
        )
    if isinstance(renderable, Group):
        return "\n".join(_logical_plain(child) for child in renderable.renderables)
    plain = getattr(renderable, "plain", None)
    if isinstance(plain, str):
        return plain
    code = getattr(renderable, "code", None)
    if isinstance(code, str):
        return code
    return str(renderable)


def assert_logical_section_is_compact(
    renderable: Any,
    heading: str,
    first_content_prefix: str,
) -> None:
    """Assert that logical text has no spacer after a section heading."""
    plain = _logical_plain(renderable)
    lines = plain.splitlines()
    heading_index = lines.index(heading)
    assert lines[heading_index + 1].startswith(first_content_prefix)
    assert f"{heading}\n\n" not in plain


def assert_rendered_section_is_compact(
    renderable: object,
    heading: str,
    first_content_prefix: str,
    *,
    widths: tuple[int, ...] = (60, 120),
) -> None:
    """Assert compact section spacing after Rich renders Group boundaries."""
    for width in widths:
        output = StringIO()
        console = Console(file=output, width=width, color_system=None)
        console.print(renderable, end="")
        lines = output.getvalue().splitlines()
        heading_index = lines.index(heading)
        assert lines[heading_index + 1].startswith(first_content_prefix)


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
