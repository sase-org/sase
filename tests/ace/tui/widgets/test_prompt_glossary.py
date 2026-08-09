"""Tests for prompt glossary highlighting, preview, and jumps."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.color import Color
from rich.style import Style

from sase.ace.testing import PromptPage
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._jinja_highlight import _MAX_OVERLAY_LINES
from sase.ace.tui.widgets._vim_search import find_search_matches
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    _EditorGlossaryProject,
    _GlossaryConfigSignature,
)

from ._completion_helpers import CompletionTestApp


async def _wait_for(
    page: PromptPage,
    predicate: Callable[[], bool],
    *,
    attempts: int = 20,
) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await page.pause()
    assert predicate()


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], PreviewPanelModal)


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


def _install_warm_glossary(
    monkeypatch: pytest.MonkeyPatch,
    app: Any,
    catalog: EditorGlossaryCatalog,
) -> None:
    monkeypatch.setattr(
        app,
        "get_prompt_glossary_catalog",
        lambda _context, *, schedule=True: catalog,
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


async def test_glossary_overlay_marks_spans_and_registers_styles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Ask Agent Clan to inspect the workspace"
        catalog = _catalog_for_text(text, tmp_path, "Agent Clan")
        _install_warm_glossary(monkeypatch, app, catalog)

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


async def test_glossary_overlay_order_keeps_search_and_code_in_front(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "`Agent Clan` Agent Clan"
        catalog = _catalog_for_text(text, tmp_path, "Agent Clan", occurrence_count=2)
        _install_warm_glossary(monkeypatch, app, catalog)

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
        catalog = _catalog_for_text(text, tmp_path, "Agent Clan")
        _install_warm_glossary(monkeypatch, page.ta.app, catalog)

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
        catalog = _catalog_for_text(text, tmp_path, "Agent Clan")
        _install_warm_glossary(monkeypatch, page.ta.app, catalog)

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
        catalog = _catalog_for_text(
            text,
            tmp_path,
            "Agent Clan",
            occurrence_count=2,
        )
        _install_warm_glossary(monkeypatch, page.ta.app, catalog)

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
        ta._build_highlight_map()

        assert getter_schedules == [False]
        assert warmed == []
        assert "glossary.term" not in _highlight_names(ta)


async def test_glossary_overlay_skips_large_buffers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "Agent Clan\n" * (_MAX_OVERLAY_LINES + 1)
        catalog = _catalog_for_text("Agent Clan", tmp_path, "Agent Clan")
        _install_warm_glossary(monkeypatch, app, catalog)

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
        _install_warm_glossary(
            monkeypatch, app, _catalog_for_text(text, tmp_path, text)
        )

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


async def test_k_on_glossary_term_pushes_markdown_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask Agent Clan to coordinate"
    catalog = _catalog_for_text(text, tmp_path, "Agent Clan")

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        _install_warm_glossary(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("word lookup must not run for glossary terms")
            ),
        )

        await page.press("K")
        await _wait_for(page, lambda: _top_is_preview(page))

        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        payload = modal._payload
        assert payload.kind_label == "glossary"
        assert payload.default_view == "rendered"
        assert payload.title == "Agent Clan"
        assert payload.source_path == str(tmp_path / "sase.yml")
        assert "# Agent Clan" in payload.content
        assert "A named, rootless container for coordinated agents." in payload.content
        assert "Aliases: clan, agent clans" in payload.content
        assert "Project: sase" in payload.content
        assert str(tmp_path / "sase.yml") in payload.content
        assert page.ta._prompt_preview_request_id == 0


async def test_k_on_cold_glossary_defers_without_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[PromptGlossaryContext] = []
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage("Agent Clan", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta.app,
            "get_prompt_glossary_catalog",
            lambda _context, *, schedule=True: None,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "is_prompt_glossary_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "warm_prompt_glossary_catalog",
            warmed.append,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("cold glossary lookup must not fall through")
            ),
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await page.pause()

        assert len(warmed) == 1
        assert notifications == [
            ("Glossary catalog is still loading; try again", "warning")
        ]
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_ctrl_bracket_on_glossary_term_opens_definition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask Agent Clan to coordinate"
    catalog = _catalog_for_text(text, tmp_path, "Agent Clan")
    calls: list[tuple[str, Any]] = []

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.is_tmux_session",
        lambda: False,
    )
    monkeypatch.setattr(
        PromptTextArea,
        "_perform_jump_action",
        lambda self, choice, payload: calls.append((choice, payload)),
    )

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        _install_warm_glossary(monkeypatch, page.ta.app, catalog)

        await page.press("ctrl+right_square_bracket")
        await _wait_for(page, lambda: bool(calls))

        choice, payload = calls[0]
        assert choice == "editor"
        assert payload.kind_label == "glossary"
        assert payload.title == "Agent Clan"
        assert payload.source_path == str(tmp_path / "sase.yml")
        assert payload.line == 8
        assert payload.col == 5
        assert payload.loadable_markdown is None
        assert page.ta._prompt_jump_request_id == 0


async def test_ctrl_bracket_on_cold_glossary_defers_without_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[PromptGlossaryContext] = []
    notifications: list[tuple[str, str | None]] = []

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_jump.resolve_jump_target",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cold glossary lookup must not resolve")
        ),
    )

    async with PromptPage("Agent Clan", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta.app,
            "get_prompt_glossary_catalog",
            lambda _context, *, schedule=True: None,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "is_prompt_glossary_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "warm_prompt_glossary_catalog",
            warmed.append,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("ctrl+right_square_bracket")
        await page.pause()

        assert len(warmed) == 1
        assert notifications == [
            ("Glossary catalog is still loading; try again", "warning")
        ]
        assert page.ta._prompt_jump_request_id == 0


class _FakeCompiledGlossary:
    def __init__(self, spans: tuple[dict[str, Any], ...]) -> None:
        self._spans = spans

    def scan(self, _text: str) -> list[dict[str, Any]]:
        return list(self._spans)

    def lookup(
        self,
        _text: str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        for span in self._spans:
            editor_range = span["range"]
            start = editor_range["start"]
            end = editor_range["end"]
            if (
                start["line"] <= line <= end["line"]
                and (line > start["line"] or character >= start["character"])
                and (line < end["line"] or character < end["character"])
            ):
                return span
        return None


def _catalog_for_text(
    text: str,
    tmp_path: Path,
    term: str,
    *,
    occurrence_count: int = 1,
) -> EditorGlossaryCatalog:
    spans = tuple(
        _span_wire(text, term, start, start + len(term))
        for start in (_occurrence_offsets(text, term, occurrence_count))
    )
    config_path = tmp_path / "sase.yml"
    entry = GlossaryEntry(
        index=0,
        term=term,
        normalized_term=term.casefold(),
        definition="A named, rootless container for coordinated agents.",
        configured_aliases=("clan", "agent clans"),
        effective_aliases=("agent clan", "clan", "agent clans"),
        source={
            "config_path": str(config_path),
            "definition_range": {
                "start": {"line": 7, "character": 4},
                "end": {"line": 7, "character": 58},
            },
        },
    )
    return EditorGlossaryCatalog(
        schema_version=1,
        project=_EditorGlossaryProject(
            key="sase",
            name="sase",
            aliases=("sase-org",),
            workspace_dir=tmp_path,
        ),
        config_path=config_path,
        config_signature=_GlossaryConfigSignature(
            path=str(config_path),
            mtime_ns=1,
            size=256,
        ),
        catalog=GlossaryCatalog(schema_version=1, entries=(entry,)),
        compiled=_FakeCompiledGlossary(spans),
    )


def _occurrence_offsets(text: str, term: str, count: int) -> tuple[int, ...]:
    offsets: list[int] = []
    start = 0
    while len(offsets) < count:
        found = text.find(term, start)
        assert found != -1
        offsets.append(found)
        start = found + len(term)
    return tuple(offsets)


def _span_wire(
    text: str,
    term: str,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "term": term,
        "entry_index": 0,
        "alias_index": 0,
        "alias": term,
        "matched_text": text[start:end],
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": _editor_range(text, start, end),
    }


def _editor_range(text: str, start: int, end: int) -> dict[str, Any]:
    return {
        "start": _editor_position(text, start),
        "end": _editor_position(text, end),
    }


def _editor_position(text: str, offset: int) -> dict[str, int]:
    prefix = text[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return {
        "line": line,
        "character": _utf16_character(text[line_start:offset]),
    }


def _utf16_character(text: str) -> int:
    return sum(2 if ord(char) > 0xFFFF else 1 for char in text)
