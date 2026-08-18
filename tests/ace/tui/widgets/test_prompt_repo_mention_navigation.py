"""Tests for prompt repo-mention preview actions."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.repo_preview_modal import RepoPreviewModal
from sase.ace.tui.repo_mention_catalog import PromptRepoMentionContext

from ._prompt_repo_mention_helpers import catalog_for_text, install_warm_repo_mentions


def _top_is_preview(page: PromptPage) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], RepoPreviewModal)


def _render_text(renderable: object) -> str:
    console = Console(file=io.StringIO(), width=100, record=True)
    console.print(renderable)
    return console.export_text()


async def test_k_on_repo_mention_pushes_repo_preview_card(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core")

    async with PromptPage(text, cursor=(0, 6), size=(80, 24)) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("word lookup must not run for repo mentions")
            ),
        )

        await page.press("K")
        await page.wait_for(lambda: _top_is_preview(page))

        modal = page.ta.app.screen_stack[-1]
        assert isinstance(modal, RepoPreviewModal)
        assert modal._mention.identifier == "sase-core"
        assert modal._matched_text == "sase-core"
        title_text = _render_text(modal._build_title())
        assert "REPO" in title_text
        assert "sase-core" in title_text
        assert "matched" not in title_text
        assert page.ta._prompt_preview_request_id == 0


async def test_k_on_cold_repo_catalog_defers_without_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warmed: list[PromptRepoMentionContext] = []
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage("sase-core", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta.app,
            "get_prompt_repo_mention_catalog",
            lambda _context, *, schedule=True: None,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "is_prompt_repo_mention_catalog_warm",
            lambda _context: False,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta.app,
            "warm_prompt_repo_mention_catalog",
            warmed.append,
            raising=False,
        )
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: (_ for _ in ()).throw(
                AssertionError("cold repo lookup must not fall through")
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
            ("Repo catalog is still loading; try again", "warning")
        ]
        assert page.ta._prompt_preview_request_id == 0
        assert not _top_is_preview(page)


async def test_k_miss_on_repo_mention_falls_through_to_word_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    text = "Ask sase-core to inspect the workspace"
    catalog = catalog_for_text(text, tmp_path, "sase-core")
    calls: list[bool] = []

    async with PromptPage(
        text,
        cursor=(0, text.index("inspect")),
        size=(80, 24),
    ) as page:
        install_warm_repo_mentions(monkeypatch, page.ta.app, catalog)
        monkeypatch.setattr(
            page.ta,
            "_lookup_word_under_cursor",
            lambda: calls.append(True) or False,
        )

        await page.press("K")
        await page.pause()

        assert calls == [True]
        assert not _top_is_preview(page)
