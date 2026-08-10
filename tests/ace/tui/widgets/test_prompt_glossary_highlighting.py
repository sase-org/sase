"""Tests for prompt glossary highlighting and caching."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.color import Color
from rich.style import Style

from sase.ace.testing import PromptPage
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import find_search_matches
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._prompt_glossary_helpers import (
    catalog_for_text,
    catalog_for_wrapped_text,
    dynamic_catalog_for_term,
    install_warm_glossary,
)


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _glossary_highlights(ta: PromptTextArea) -> list[tuple[int, int, int, str]]:
    return [
        (row, start, end, name)
        for row, spans in ta._highlights.items()
        for start, end, name in spans
        if name.startswith("glossary.")
    ]


def _style_at_text_offset(
    text_area: PromptTextArea,
    y: int,
    offset: int,
) -> Style | None:
    cell = text_area.gutter_width + offset
    strip = text_area.render_line(y).crop(cell, cell + 1)
    for segment in strip._segments:
        if segment.control is None and segment.style is not None:
            return segment.style
    return None


async def test_glossary_overlay_marks_spans_and_registers_styles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Ask Agent Clan to inspect the workspace"
        catalog = catalog_for_text(text, tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        ta._refresh_prompt_glossary_context(schedule=False)
        ta._build_highlight_map()

        assert (0, 4, 14, "glossary.term") in _glossary_highlights(ta)
        style = ta._theme.syntax_styles["glossary.term"]
        assert style.bold is True
        assert style.underline is True
        assert style.color not in {
            Color.parse(app.current_theme.warning),
            Color.parse(app.current_theme.error),
        }


async def test_glossary_overlay_uses_trimmed_segments_for_wrapped_terms(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Ask Agent\n  Clan to coordinate"
        catalog = catalog_for_wrapped_text(text, tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        ta._refresh_prompt_glossary_context(schedule=False)
        ta._build_highlight_map()

        assert _glossary_highlights(ta) == [
            (0, 4, 9, "glossary.term"),
            (1, 2, 6, "glossary.term"),
        ]


async def test_glossary_overlay_order_keeps_search_and_code_in_front(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "`Agent Clan` Agent Clan"
        catalog = catalog_for_text(text, tmp_path, "Agent Clan", occurrence_count=2)
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        ta._set_search_highlights(
            find_search_matches(text, "Agent Clan"),
            current_index=1,
            refresh=False,
        )
        ta._refresh_prompt_glossary_context(schedule=False)
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert "glossary.term" in names
        assert names.index("glossary.term") < names.index("codeblock.inline")
        assert names.index("glossary.term") < names.index("search.current")


async def test_glossary_overlay_wins_over_misspelling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Agent Clan"
    async with PromptPage(
        text,
        misspellings=["agent", "clan"],
        mode="insert",
    ) as page:
        catalog = catalog_for_text(text, tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, page.ta.app, catalog)

        page.ta._refresh_prompt_glossary_context(schedule=False)
        page.ta._build_highlight_map()

        names = _highlight_names(page.ta)
        assert names.index("spell.misspelled") < names.index("glossary.term")


async def test_glossary_misspelling_overlap_renders_as_glossary_style(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Agent Clan"
    async with PromptPage(
        text,
        cursor=(0, len(text)),
        misspellings=["agent", "clan"],
        mode="insert",
        size=(40, 8),
    ) as page:
        catalog = catalog_for_text(text, tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, page.ta.app, catalog)

        page.ta._refresh_prompt_glossary_context(schedule=False)
        page.ta._build_highlight_map()
        await page.pause()

        rendered = _style_at_text_offset(page.ta, 0, 0)
        glossary = page.ta._theme.syntax_styles["glossary.term"]
        assert rendered is not None
        assert rendered.color == glossary.color
        assert rendered.bold is True
        assert rendered.underline is True


async def test_glossary_underline_is_cleared_inside_inline_code_chip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "`Agent Clan` Agent Clan"
    async with PromptPage(
        text,
        cursor=(0, len(text)),
        mode="insert",
        size=(50, 8),
    ) as page:
        catalog = catalog_for_text(
            text,
            tmp_path,
            "Agent Clan",
            occurrence_count=2,
        )
        install_warm_glossary(monkeypatch, page.ta.app, catalog)

        page.ta._refresh_prompt_glossary_context(schedule=False)
        page.ta._build_highlight_map()
        await page.pause()

        inside_chip = _style_at_text_offset(page.ta, 0, 1)
        outside_chip = _style_at_text_offset(page.ta, 0, text.rindex("Agent Clan"))
        assert inside_chip is not None
        assert inside_chip.underline is False
        assert outside_chip is not None
        assert outside_chip.underline is True


async def test_glossary_overlay_cold_render_defers_without_warming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        getter_schedules: list[bool] = []
        warmed: list[PromptGlossaryContext] = []

        monkeypatch.setattr(
            app,
            "get_prompt_glossary_catalog",
            lambda _context, *, schedule=True: (
                getter_schedules.append(schedule) or None
            ),
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_glossary_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_glossary_catalog",
            warmed.append,
            raising=False,
        )

        ta.load_text("Agent Clan")
        ta._refresh_prompt_glossary_context(schedule=False)
        getter_schedules.clear()
        ta._build_highlight_map()

        assert getter_schedules == [False]
        assert warmed == []
        assert "glossary.term" not in _highlight_names(ta)


async def test_glossary_overlay_survives_real_insert_before_changed_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        text = "Ask Agent Clan to inspect the workspace"
        catalog = dynamic_catalog_for_term(tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        await pilot.pause()
        ta._build_highlight_map()
        assert (0, 4, 14, "glossary.term") in _glossary_highlights(ta)

        ta.cursor_location = (0, 0)
        ta.insert("Now ")

        assert ta.text == "Now " + text
        assert (0, 8, 18, "glossary.term") in _glossary_highlights(ta)


async def test_glossary_overlay_survives_repeated_real_inserts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        text = "Agent Clan should coordinate"
        catalog = dynamic_catalog_for_term(tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        await pilot.pause()
        ta._build_highlight_map()

        ta.cursor_location = (0, 0)
        prefix = ""
        for character in "abc":
            ta.insert(character)
            prefix += character
            assert (0, len(prefix), len(prefix) + 10, "glossary.term") in (
                _glossary_highlights(ta)
            )


async def test_glossary_context_change_repaints_highlights(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    old_context = PromptGlossaryContext(project_ref="old", launch_workspace=None)
    new_context = PromptGlossaryContext(project_ref="new", launch_workspace=None)
    old_catalog = dynamic_catalog_for_term(
        tmp_path,
        "Agent Clan",
        project_key="old",
        project_name="old",
    )
    new_catalog = dynamic_catalog_for_term(
        tmp_path,
        "Workspace",
        project_key="new",
        project_name="new",
    )
    context_state = {"value": old_context}
    catalogs = {
        old_context: old_catalog,
        new_context: new_catalog,
    }

    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Agent Clan Workspace")
        monkeypatch.setattr(
            ta,
            "_compute_prompt_glossary_context",
            lambda: context_state["value"],
        )
        monkeypatch.setattr(
            app,
            "get_prompt_glossary_catalog",
            lambda context, *, schedule=True: catalogs[context],
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_glossary_catalog_warm",
            lambda _context: True,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_glossary_catalog",
            lambda _context: None,
            raising=False,
        )

        ta._refresh_prompt_glossary_context(schedule=False)
        assert _glossary_highlights(ta) == [(0, 0, 10, "glossary.term")]

        context_state["value"] = new_context
        ta._refresh_prompt_glossary_context(schedule=False)

        assert _glossary_highlights(ta) == [(0, 11, 20, "glossary.term")]


async def test_glossary_scan_is_cached_by_text_and_compiled_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_catalog = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    second_catalog = dynamic_catalog_for_term(tmp_path, "Agent Clan")
    current_catalog = {"value": first_catalog}

    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Agent Clan")
        monkeypatch.setattr(
            app,
            "get_prompt_glossary_catalog",
            lambda _context, *, schedule=True: current_catalog["value"],
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_glossary_catalog_warm",
            lambda _context: True,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_glossary_catalog",
            lambda _context: None,
            raising=False,
        )
        ta._prompt_glossary_context_cache = PromptGlossaryContext(
            project_ref=None,
            launch_workspace=None,
        )

        ta._build_highlight_map()
        ta._build_highlight_map()
        assert first_catalog.compiled.scan_calls == 1

        ta.cursor_location = (0, 0)
        ta.insert("Ask ")
        ta._build_highlight_map()
        assert first_catalog.compiled.scan_calls == 2

        current_catalog["value"] = second_catalog
        ta._build_highlight_map()

        assert first_catalog.compiled.scan_calls == 2
        assert second_catalog.compiled.scan_calls == 1


async def test_glossary_overlay_skips_large_buffers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Agent Clan\n" * (_MAX_OVERLAY_LINES + 1)
        catalog = catalog_for_text("Agent Clan", tmp_path, "Agent Clan")
        install_warm_glossary(monkeypatch, app, catalog)

        ta.load_text(text)
        ta._refresh_prompt_glossary_context(schedule=False)
        ta._build_highlight_map()

        assert "glossary.term" not in _highlight_names(ta)


async def test_glossary_style_reregisters_after_theme_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        text = "Agent Clan"
        install_warm_glossary(monkeypatch, app, catalog_for_text(text, tmp_path, text))

        ta.load_text(text)
        ta._refresh_prompt_glossary_context(schedule=False)
        ta._build_highlight_map()
        sentinel = Style(color="red", underline=True)
        ta._theme.syntax_styles["glossary.term"] = sentinel

        app.theme = "textual-light"
        await pilot.pause()

        after = ta._theme.syntax_styles["glossary.term"]
        assert after != sentinel
        assert after.bold is True
        assert after.underline is True
        assert after.color != Color.parse("red")
