"""Tests for the transient prompt yank highlight."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.testing import PromptPage, VimEditorPage
from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import find_search_matches
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.xprompt import jinja_inspect

from ._completion_helpers import CompletionTestApp


class _FakeTimer:
    def __init__(self, callback: Callable[[], None]) -> None:
        self.callback = callback
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _capture_timers(monkeypatch, ta: PromptTextArea) -> list[_FakeTimer]:
    timers: list[_FakeTimer] = []
    original_set_timer = ta.set_timer

    def set_timer(delay: float, callback: Callable[[], None]):
        if delay != 0.2:
            return original_set_timer(delay, callback)
        timer = _FakeTimer(callback)
        timers.append(timer)
        return timer

    monkeypatch.setattr(ta, "set_timer", set_timer)
    return timers


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


@pytest.mark.parametrize(
    ("text", "cursor", "keys", "expected_span", "expected_register"),
    [
        ("one two three", (0, 0), ("y", "w"), (0, 4), "one "),
        ("hello world foo", (0, 7), ("y", "i", "w"), (6, 11), "world"),
        ("foo(bar) baz", (0, 3), ("y", "f", ")"), (3, 8), "(bar)"),
        ("aaa\nbbb\nccc\nddd", (1, 0), ("2", "Y"), (4, 11), "bbb\nccc"),
    ],
)
async def test_charwise_yanks_flash_exact_copied_range(
    monkeypatch,
    text: str,
    cursor: tuple[int, int],
    keys: tuple[str, ...],
    expected_span: tuple[int, int],
    expected_register: str,
) -> None:
    async with PromptPage(text, cursor=cursor) as page:
        _capture_timers(monkeypatch, page.ta)
        await page.press(*keys)

        assert page.text == text
        assert page.ta._vim_register.text == expected_register
        assert page.ta._yank_flash_span == expected_span
        assert "yank.flash" in _highlight_names(page.ta)


@pytest.mark.parametrize(
    ("text", "cursor", "keys", "expected_span"),
    [
        ("aaa\nbbb\nccc", (1, 1), ("y", "y"), (4, 7)),
        ("aaa\nbbb\nccc\nddd", (1, 1), ("V", "j", "y"), (4, 11)),
    ],
)
async def test_linewise_yanks_flash_full_lines(
    monkeypatch,
    text: str,
    cursor: tuple[int, int],
    keys: tuple[str, ...],
    expected_span: tuple[int, int],
) -> None:
    async with PromptPage(text, cursor=cursor) as page:
        _capture_timers(monkeypatch, page.ta)
        await page.press(*keys)

        assert page.text == text
        assert page.ta._yank_flash_span == expected_span
        assert "yank.flash" in _highlight_names(page.ta)


async def test_visual_charwise_yank_flashes_selection(monkeypatch) -> None:
    async with PromptPage("abcde", cursor=(0, 2)) as page:
        _capture_timers(monkeypatch, page.ta)
        await page.press("v", "h", "y")

        assert page.text == "abcde"
        assert page.ta._vim_register.text == "bc"
        assert page.ta._yank_flash_span == (1, 3)
        assert "yank.flash" in _highlight_names(page.ta)


async def test_yank_flash_expiry_clears_only_overlay(monkeypatch) -> None:
    async with PromptPage("one two three") as page:
        timers = _capture_timers(monkeypatch, page.ta)
        await page.press("y", "w")
        generation = page.ta._yank_flash_generation

        page.ta._clear_yank_flash(generation)

        assert page.ta._yank_flash_span is None
        assert page.ta._yank_flash_timer is None
        assert "yank.flash" not in _highlight_names(page.ta)
        assert page.text == "one two three"
        assert page.ta._vim_register.text == "one "
        assert len(timers) == 1


async def test_rapid_reyank_replaces_flash_and_ignores_stale_timer(
    monkeypatch,
) -> None:
    async with PromptPage("one two three") as page:
        timers = _capture_timers(monkeypatch, page.ta)
        await page.press("y", "w")
        old_generation = page.ta._yank_flash_generation
        page.cursor = (0, 4)

        await page.press("y", "w")

        assert len(timers) == 2
        assert timers[0].stopped
        assert page.ta._yank_flash_span == (4, 8)
        page.ta._clear_yank_flash(old_generation)
        assert page.ta._yank_flash_span == (4, 8)
        assert "yank.flash" in _highlight_names(page.ta)


async def test_yank_overlay_coexists_with_search_and_jinja(
    monkeypatch,
) -> None:
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _capture_timers(monkeypatch, ta)
        ta.load_text("Hello {{ root }} root")
        ta._set_search_highlights(
            find_search_matches(ta.text, "root"),
            current_index=1,
        )
        ta._flash_yank((0, 9), (0, 13))
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert "jinja.variable" in names
        assert "search.match" in names
        assert "search.current" in names
        assert "yank.flash" in names
        assert names[-1] == "yank.flash"
        assert "yank.flash" in ta._theme.syntax_styles


async def test_yank_overlay_skips_large_buffers(monkeypatch) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        _capture_timers(monkeypatch, ta)
        ta.load_text("needle\n" * (_MAX_OVERLAY_LINES + 1))
        ta._flash_yank((0, 0), (0, 6))
        ta._build_highlight_map()

        assert "yank.flash" not in _highlight_names(ta)


@pytest.mark.parametrize("keys", [("d", "w"), ("c", "w")])
async def test_delete_and_change_do_not_flash(
    monkeypatch, keys: tuple[str, ...]
) -> None:
    async with PromptPage("one two") as page:
        timers = _capture_timers(monkeypatch, page.ta)
        await page.press(*keys)

        assert page.ta._yank_flash_span is None
        assert "yank.flash" not in _highlight_names(page.ta)
        assert timers == []


async def test_empty_line_yank_does_not_flash(monkeypatch) -> None:
    async with PromptPage("") as page:
        timers = _capture_timers(monkeypatch, page.ta)
        await page.press("y", "y")

        assert page.ta._yank_flash_span is None
        assert "yank.flash" not in _highlight_names(page.ta)
        assert timers == []


async def test_single_line_vim_text_area_uses_inert_yank_hook() -> None:
    async with VimEditorPage(
        "one two",
        widget_cls=SingleLineVimTextArea,
    ) as page:
        await page.press("y", "w")

        names = [name for row in page.ta._highlights.values() for *_range, name in row]
        assert page.ta._vim_register.text == "one "
        assert "yank.flash" not in names
        assert not hasattr(page.ta, "_yank_flash_span")
