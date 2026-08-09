"""Tests for prompt glossary preview and jump actions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.glossary_catalog import PromptGlossaryContext
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._prompt_glossary_helpers import catalog_for_text, install_warm_glossary


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


async def test_k_on_glossary_term_pushes_markdown_preview(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask Agent Clan to coordinate"
    catalog = catalog_for_text(text, tmp_path, "Agent Clan")

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_glossary(monkeypatch, page.ta.app, catalog)
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
        assert "ALIASES: clan, agent clans" in payload.content
        assert "Aliases:" not in payload.content
        assert "PROJECT: sase" in payload.content
        assert "SOURCE:" in payload.content
        assert str(tmp_path / "sase.yml") in payload.content
        assert page.ta._prompt_preview_request_id == 0


async def test_k_on_glossary_alias_keeps_reference_without_matched_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask clan to coordinate"
    catalog = catalog_for_text(text, tmp_path, "clan", entry_term="Agent Clan")

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_glossary(monkeypatch, page.ta.app, catalog)

        await page.press("K")
        await _wait_for(page, lambda: _top_is_preview(page))

        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        payload = modal._payload
        assert payload.title == "Agent Clan"
        assert payload.reference == "clan"
        assert "Matched:" not in payload.content


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
    catalog = catalog_for_text(text, tmp_path, "Agent Clan")
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
        install_warm_glossary(monkeypatch, page.ta.app, catalog)

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
