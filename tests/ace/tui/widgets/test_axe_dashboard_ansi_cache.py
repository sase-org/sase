"""Render cache for the axe dashboard output section.

The cache lives in :mod:`sase.ace.tui.util.axe_log_renderer` after the Phase 3
split; these tests pin its tail-biased, per-slot behavior and that the ANSI
and semantic paths cache independently.
"""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.util import axe_log_renderer


def _reset_cache() -> None:
    axe_log_renderer._render_cache.clear()


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
        first = axe_log_renderer.render_axe_output("axe-output", sample, "ansi")
        second = axe_log_renderer.render_axe_output("axe-output", sample, "ansi")

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
        axe_log_renderer.render_axe_output("axe-output", base, "ansi")
        axe_log_renderer.render_axe_output("axe-output", grown, "ansi")

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
        axe_log_renderer.render_axe_output("axe-output", payload, "ansi")
        axe_log_renderer.render_axe_output("lumberjack:foo", payload, "ansi")
        # Re-render the same source — cached.
        axe_log_renderer.render_axe_output("axe-output", payload, "ansi")

    assert call_count == 2


def test_semantic_and_ansi_paths_cache_independently() -> None:
    """Same source_id + payload but different source_type must not collide.

    The semantic path doesn't call ``Text.from_ansi`` at all, so an
    ``ansi`` render of the same slot still has to fall through to a fresh
    parse instead of returning the semantic Text.
    """
    _reset_cache()
    payload = "[2026-01-01 00:00:00] [hooks] success\n"

    ansi_text = axe_log_renderer.render_axe_output("lumberjack:hooks", payload, "ansi")
    semantic_text = axe_log_renderer.render_axe_output(
        "lumberjack:hooks", payload, "lumberjack"
    )

    assert ansi_text is not semantic_text
    # Cached re-renders return the same instance per slot.
    assert (
        axe_log_renderer.render_axe_output("lumberjack:hooks", payload, "ansi")
        is ansi_text
    )
    assert (
        axe_log_renderer.render_axe_output("lumberjack:hooks", payload, "lumberjack")
        is semantic_text
    )
