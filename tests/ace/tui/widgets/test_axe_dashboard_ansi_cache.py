"""ANSI parse cache for the axe dashboard output section."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.widgets import axe_dashboard


def _reset_cache() -> None:
    axe_dashboard._ansi_parse_cache.clear()


def test_unchanged_output_skips_from_ansi_call() -> None:
    """A second call with identical output reuses the cached parse."""
    _reset_cache()
    sample = "\x1b[32mhello\x1b[0m world\n"

    call_count = 0
    real_from_ansi = Text.from_ansi

    def _counting_from_ansi(text: str) -> Text:
        nonlocal call_count
        call_count += 1
        return real_from_ansi(text)

    with patch.object(Text, "from_ansi", staticmethod(_counting_from_ansi)):
        first = axe_dashboard._render_ansi_cached("axe-output", sample)
        second = axe_dashboard._render_ansi_cached("axe-output", sample)

    assert first is second
    assert call_count == 1


def test_growth_invalidates_cache() -> None:
    """Appending to the output forces a re-parse."""
    _reset_cache()
    base = "line one\n"
    grown = base + "line two\n"

    call_count = 0
    real_from_ansi = Text.from_ansi

    def _counting_from_ansi(text: str) -> Text:
        nonlocal call_count
        call_count += 1
        return real_from_ansi(text)

    with patch.object(Text, "from_ansi", staticmethod(_counting_from_ansi)):
        axe_dashboard._render_ansi_cached("axe-output", base)
        axe_dashboard._render_ansi_cached("axe-output", grown)

    assert call_count == 2


def test_distinct_source_ids_cache_independently() -> None:
    """Different source slots don't collide on the same payload."""
    _reset_cache()
    payload = "shared text\n"

    call_count = 0
    real_from_ansi = Text.from_ansi

    def _counting_from_ansi(text: str) -> Text:
        nonlocal call_count
        call_count += 1
        return real_from_ansi(text)

    with patch.object(Text, "from_ansi", staticmethod(_counting_from_ansi)):
        axe_dashboard._render_ansi_cached("axe-output", payload)
        axe_dashboard._render_ansi_cached("lumberjack:foo", payload)
        # Re-render the same source — cached.
        axe_dashboard._render_ansi_cached("axe-output", payload)

    assert call_count == 2
