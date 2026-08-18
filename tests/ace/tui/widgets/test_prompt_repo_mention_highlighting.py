"""Tests for prompt repo-mention highlighting and caching."""

from __future__ import annotations

from pathlib import Path

import pytest
from rich.color import Color
from rich.style import Style

from sase.ace.testing import PromptPage
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext
from sase.ace.tui.widgets._jinja_highlight import (
    _MAX_OVERLAY_BYTES,
    _MAX_OVERLAY_LINES,
)
from sase.ace.tui.widgets._prompt_repo_mentions import _ColdRepoCatalogType
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._prompt_glossary_helpers import catalog_for_text as glossary_catalog_for_text
from ._prompt_glossary_helpers import install_warm_glossary
from ._prompt_repo_mention_helpers import (
    catalog_for_text,
    dynamic_catalog_for_identifier,
    install_warm_repo_mentions,
)


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _repo_mention_highlights(ta: PromptTextArea) -> list[tuple[int, int, int, str]]:
    return [
        (row, start, end, name)
        for row, spans in ta._highlights.items()
        for start, end, name in spans
        if name.startswith("repo.")
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


async def test_repo_mention_overlay_marks_spans_and_registers_styles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Ask sase-core to inspect the workspace"
        catalog = catalog_for_text(text, tmp_path, "sase-core")
        install_warm_repo_mentions(monkeypatch, app, catalog)

        ta.load_text(text)
        ta._refresh_prompt_repo_mention_context(schedule=False)
        ta._build_highlight_map()

        assert (0, 4, 13, "repo.mention") in _repo_mention_highlights(ta)
        style = ta._theme.syntax_styles["repo.mention"]
        assert style.bold is True
        assert style.underline is True
        assert style.color not in {
            Color.parse(app.current_theme.warning),
            Color.parse(app.current_theme.error),
        }


async def test_repo_mention_overlay_cold_render_defers_without_warming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        getter_schedules: list[bool] = []
        warmed: list[PromptRepoMentionContext] = []

        monkeypatch.setattr(
            app,
            "get_prompt_repo_mention_catalog",
            lambda _context, *, schedule=True: (
                getter_schedules.append(schedule) or None
            ),
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_repo_mention_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_repo_mention_catalog",
            warmed.append,
            raising=False,
        )

        ta.load_text("sase-core")
        ta._refresh_prompt_repo_mention_context(schedule=False)
        getter_schedules.clear()
        ta._build_highlight_map()

        assert getter_schedules == [False]
        assert warmed == []
        assert "repo.mention" not in _highlight_names(ta)


async def test_repo_mention_cold_catalog_schedules_exactly_one_warm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        warmed: list[PromptRepoMentionContext] = []
        warming: set[PromptRepoMentionContext] = set()

        def _warm(context: PromptRepoMentionContext) -> None:
            if context in warming:
                return
            warming.add(context)
            warmed.append(context)

        monkeypatch.setattr(
            app,
            "get_prompt_repo_mention_catalog",
            lambda _context, *, schedule=True: None,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_repo_mention_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_repo_mention_catalog",
            _warm,
            raising=False,
        )

        ta.load_text("sase-core")
        ta.cursor_location = (0, 0)
        ta._refresh_prompt_repo_mention_context(schedule=False)

        first = ta._repo_mention_under_cursor(schedule=True)
        second = ta._repo_mention_under_cursor(schedule=True)

        assert isinstance(first, _ColdRepoCatalogType)
        assert isinstance(second, _ColdRepoCatalogType)
        assert len(warmed) == 1


async def test_repo_mention_under_cursor_returns_span_when_warm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Ask sase-core to inspect the workspace"
        catalog = catalog_for_text(text, tmp_path, "sase-core")
        install_warm_repo_mentions(monkeypatch, app, catalog)

        ta.load_text(text)
        ta.cursor_location = (0, 6)
        ta._refresh_prompt_repo_mention_context(schedule=False)

        match = ta._repo_mention_under_cursor(schedule=False)
        assert match is not None
        assert not isinstance(match, _ColdRepoCatalogType)
        found_catalog, span = match
        assert found_catalog is catalog
        assert span.mention.identifier == "sase-core"
        assert span.matched_text == "sase-core"


async def test_repo_mention_overlay_skips_large_buffers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        oversized_lines = "sase-core\n" * (_MAX_OVERLAY_LINES + 1)
        oversized_bytes = "é" * (_MAX_OVERLAY_BYTES // 2 + 1) + " sase-core"
        catalog = catalog_for_text("sase-core", tmp_path, "sase-core")
        install_warm_repo_mentions(monkeypatch, app, catalog)

        ta.load_text(oversized_lines)
        ta._refresh_prompt_repo_mention_context(schedule=False)
        ta._build_highlight_map()
        assert "repo.mention" not in _highlight_names(ta)

        ta.load_text(oversized_bytes)
        ta._refresh_prompt_repo_mention_context(schedule=False)
        ta._build_highlight_map()
        assert "repo.mention" not in _highlight_names(ta)


async def test_repo_mention_scan_is_cached_by_text_and_compiled_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first_catalog = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    second_catalog = dynamic_catalog_for_identifier(tmp_path, "sase-core")
    current_catalog = {"value": first_catalog}

    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("sase-core")
        monkeypatch.setattr(
            app,
            "get_prompt_repo_mention_catalog",
            lambda _context, *, schedule=True: current_catalog["value"],
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "is_prompt_repo_mention_catalog_warm",
            lambda _context: True,
            raising=False,
        )
        monkeypatch.setattr(
            app,
            "warm_prompt_repo_mention_catalog",
            lambda _context: None,
            raising=False,
        )
        ta._prompt_repo_mention_context_cache = PromptRepoMentionContext(
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


async def test_glossary_and_repo_mention_keep_distinct_styles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask Agent Clan to inspect sase-core"
    async with PromptPage(
        text,
        cursor=(0, len(text)),
        mode="insert",
        size=(50, 8),
    ) as page:
        install_warm_glossary(
            monkeypatch,
            page.ta.app,
            glossary_catalog_for_text(text, tmp_path, "Agent Clan"),
        )
        install_warm_repo_mentions(
            monkeypatch,
            page.ta.app,
            catalog_for_text(text, tmp_path, "sase-core"),
        )

        page.ta._refresh_prompt_glossary_context(schedule=False)
        page.ta._refresh_prompt_repo_mention_context(schedule=False)
        page.ta._build_highlight_map()
        await page.pause()

        names = _highlight_names(page.ta)
        assert "glossary.term" in names
        assert "repo.mention" in names

        glossary = page.ta._theme.syntax_styles["glossary.term"]
        repo = page.ta._theme.syntax_styles["repo.mention"]
        assert glossary.color != repo.color
        assert glossary.bold is True
        assert glossary.underline is True
        assert repo.bold is True
        assert repo.underline is True

        glossary_rendered = _style_at_text_offset(page.ta, 0, text.index("Agent Clan"))
        repo_rendered = _style_at_text_offset(page.ta, 0, text.index("sase-core"))
        assert glossary_rendered is not None
        assert repo_rendered is not None
        assert glossary_rendered.color == glossary.color
        assert repo_rendered.color == repo.color


async def test_repo_mention_overlay_wins_over_misspelling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "sase-core"
    async with PromptPage(
        text,
        misspellings=["sase-core"],
        mode="insert",
    ) as page:
        catalog = catalog_for_text(text, tmp_path, "sase-core")
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)

        page.ta._refresh_prompt_repo_mention_context(schedule=False)
        page.ta._build_highlight_map()

        names = _highlight_names(page.ta)
        assert names.index("spell.misspelled") < names.index("repo.mention")


async def test_repo_mention_style_reregisters_after_theme_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        text = "sase-core"
        install_warm_repo_mentions(
            monkeypatch, app, catalog_for_text(text, tmp_path, text)
        )

        ta.load_text(text)
        ta._refresh_prompt_repo_mention_context(schedule=False)
        ta._build_highlight_map()
        sentinel = Style(color="red", underline=True)
        ta._theme.syntax_styles["repo.mention"] = sentinel

        app.theme = "textual-light"
        await pilot.pause()

        after = ta._theme.syntax_styles["repo.mention"]
        assert after != sentinel
        assert after.bold is True
        assert after.underline is True
        assert after.color != Color.parse("red")
