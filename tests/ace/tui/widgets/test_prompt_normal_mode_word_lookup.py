"""NORMAL-mode ``K`` word definition and spellcheck tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.spellcheck_panel_modal import SpellcheckPanelModal
from sase.ace.tui.modals.word_definition_modal import WordDefinitionModal
from sase.core.word_lookup import (
    DefinitionResult,
    DefinitionSection,
    SpellCheckResult,
)


async def _wait_for(
    page: PromptPage,
    predicate: Callable[[], bool],
    *,
    attempts: int = 30,
) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await page.pause()
    assert predicate()


def _top_is(page: PromptPage, modal_type: type[object]) -> bool:
    return isinstance(page.ta.app.screen_stack[-1], modal_type)


async def test_k_on_correct_word_pushes_definition_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda word: SpellCheckResult(status="correct"),
    )

    def fake_definitions(word: str) -> DefinitionResult:
        seen.append(word)
        return DefinitionResult(
            status="ok",
            sections=(
                DefinitionSection(
                    source="WordNet (r) 3.1",
                    body="  n 1: a greeting",
                ),
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        fake_definitions,
    )

    async with PromptPage("say hello", cursor=(0, 5), size=(80, 24)) as page:
        await page.press("K")
        await _wait_for(page, lambda: _top_is(page, WordDefinitionModal))

        assert seen == ["hello"]


async def test_k_on_misspelling_digit_applies_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(
            status="misspelled",
            suggestions=("accommodate", "accommodation", "accommodated"),
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: pytest.fail("misspellings must not query dict"),
    )

    async with PromptPage(
        "fix accomodate now",
        cursor=(0, 7),
        size=(80, 24),
    ) as page:
        await page.press("K")
        await _wait_for(page, lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("3")
        await _wait_for(
            page,
            lambda: not _top_is(page, SpellcheckPanelModal),
        )

        assert page.text == "fix accommodated now"
        assert page.cursor == (0, 4)


async def test_spellcheck_escape_leaves_prompt_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(
            status="misspelled",
            suggestions=("separate", "separated"),
        ),
    )

    async with PromptPage("seperate", cursor=(0, 2), size=(80, 24)) as page:
        await page.press("K")
        await _wait_for(page, lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("escape")
        await _wait_for(
            page,
            lambda: not _top_is(page, SpellcheckPanelModal),
        )

        assert page.text == "seperate"


async def test_k_without_aspell_falls_through_to_definitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="unavailable"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: DefinitionResult(
            status="ok",
            sections=(DefinitionSection(source="GCIDE", body="  a definition"),),
        ),
    )

    async with PromptPage("word", cursor=(0, 1), size=(80, 24)) as page:
        await page.press("K")
        await _wait_for(page, lambda: _top_is(page, WordDefinitionModal))


async def test_k_without_lookup_tools_toasts_without_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="unavailable"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: DefinitionResult(status="unavailable"),
    )

    async with PromptPage("word", cursor=(0, 1), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await _wait_for(page, lambda: bool(notifications))

        assert notifications == [
            (
                "Install `dict` for word definitions "
                "(`sase doctor -D` shows optional tools)",
                "warning",
            )
        ]
        assert not _top_is(page, WordDefinitionModal)
        assert not _top_is(page, SpellcheckPanelModal)


@pytest.mark.parametrize(
    ("text", "cursor"),
    [
        ("hello, world", (0, 5)),
        ("foo_bar", (0, 1)),
    ],
)
async def test_k_on_non_word_shows_reworded_warning(
    monkeypatch: pytest.MonkeyPatch,
    text: str,
    cursor: tuple[int, int],
) -> None:
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage(text, cursor=cursor, size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )

        await page.press("K")
        await page.pause()

        assert notifications == [
            (
                "Move the cursor onto an xprompt, skill, file path, "
                "or word to look it up",
                "warning",
            )
        ]
        assert page.ta._prompt_preview_request_id == 0
