"""Tests for the sticky misspelling highlight overlay in PromptTextArea."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES


def _highlight_names(ta: Any) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


async def test_seeded_misspelling_gets_a_span() -> None:
    async with PromptPage("recieve the package", misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" in _highlight_names(page.ta)


async def test_match_is_case_insensitive() -> None:
    async with PromptPage("Recieve the package", misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" in _highlight_names(page.ta)


async def test_empty_misspelled_set_paints_nothing() -> None:
    async with PromptPage("recieve the package") as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_words_inside_inline_code_are_skipped() -> None:
    async with PromptPage("`recieve` the package", misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_words_inside_fenced_blocks_are_skipped() -> None:
    text = "before\n```\nrecieve\n```\nafter"
    async with PromptPage(text, misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_substrings_of_larger_words_are_not_matched() -> None:
    async with PromptPage("recieved the package", misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_cache_invalidates_on_generation_bump() -> None:
    async with PromptPage("recieve the package") as page:
        page.ta._build_highlight_map()
        assert "spell.misspelled" not in _highlight_names(page.ta)

        page.ta.app.record_misspelling("recieve")
        page.ta._build_highlight_map()

        assert "spell.misspelled" in _highlight_names(page.ta)


async def test_cache_invalidates_on_text_change() -> None:
    async with PromptPage("recieve the package", misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()
        assert "spell.misspelled" in _highlight_names(page.ta)

        page.text = "no misspelling here"
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_large_buffer_is_skipped() -> None:
    text = "recieve\n" * (_MAX_OVERLAY_LINES + 1)
    async with PromptPage(text, misspellings=["recieve"]) as page:
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)


async def test_highlight_disabled_paints_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with PromptPage("recieve the package", misspellings=["recieve"]) as page:
        monkeypatch.setattr(
            page.ta.app,
            "get_prompt_spellcheck_settings",
            lambda: SimpleNamespace(highlight=False),
            raising=False,
        )
        page.ta._build_highlight_map()

        assert "spell.misspelled" not in _highlight_names(page.ta)
