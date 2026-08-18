"""NORMAL-mode ``K`` word definition and spellcheck tests."""

from __future__ import annotations

import pytest

from sase.ace.testing import PromptPage
from sase.ace.tui.modals.spellcheck_panel_modal import SpellcheckPanelModal
from sase.ace.tui.modals.word_definition_modal import WordDefinitionModal
from sase.core.word_lookup import (
    AddToDictionaryResult,
    DefinitionResult,
    DefinitionSection,
    SpellCheckResult,
)


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
        await page.wait_for(lambda: _top_is(page, WordDefinitionModal))

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
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("3")
        await page.wait_for(
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
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("escape")
        await page.wait_for(
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
        await page.wait_for(lambda: _top_is(page, WordDefinitionModal))


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
        await page.wait_for(lambda: bool(notifications))

        assert notifications == [
            (
                "Install `dict` for word definitions "
                "(`sase doctor -D` shows optional tools)",
                "warning",
            )
        ]
        assert not _top_is(page, WordDefinitionModal)
        assert not _top_is(page, SpellcheckPanelModal)


async def test_k_on_misspelling_records_word_before_panel_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=("hello",)),
    )

    async with PromptPage("helllo there", cursor=(0, 2), size=(80, 24)) as page:
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))

        assert "helllo" in page.ta.app.misspelled_words()


async def test_spellcheck_escape_leaves_word_squiggled(
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
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("escape")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))

        assert "seperate" in page.ta.app.misspelled_words()
        page.ta._build_highlight_map()
        names = [name for row in page.ta._highlights.values() for *_range, name in row]
        assert "spell.misspelled" in names


async def test_k_on_misspelling_without_suggestions_opens_panel_instead_of_notifying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=()),
    )
    notifications: list[str] = []

    async with PromptPage("zzzzz word", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append(message),
        )

        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))

        assert notifications == []
        assert "zzzzz" in page.ta.app.misspelled_words()


async def test_spellcheck_accept_clears_the_squiggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=()),
    )
    notifications: list[str] = []

    async with PromptPage("Bugyi wrote this", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append(message),
        )
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("a")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))

        assert "bugyi" not in page.ta.app.misspelled_words()
        assert notifications == ["'Bugyi' will no longer be flagged as misspelled"]


async def test_spellcheck_dictionary_key_dismisses_panel_without_applying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(
            status="misspelled", suggestions=("accommodate",)
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.add_to_personal_dictionary",
        lambda _word: AddToDictionaryResult(status="added"),
    )

    async with PromptPage("fix accomodate now", cursor=(0, 7), size=(80, 24)) as page:
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("d")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))

        # The dictionary action never applies a suggestion or replaces text.
        assert page.text == "fix accomodate now"


async def test_spellcheck_dictionary_added_clears_squiggle_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.add_to_personal_dictionary",
        lambda _word: AddToDictionaryResult(status="added"),
    )
    notifications: list[str] = []

    async with PromptPage("Bugyi wrote this", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append(message),
        )
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("d")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))
        await page.wait_for(lambda: "bugyi" not in page.ta.app.misspelled_words())

        assert page.text == "Bugyi wrote this"
        assert notifications == ["Added 'Bugyi' to your aspell personal dictionary"]


async def test_spellcheck_dictionary_error_leaves_word_flagged_and_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = (
        "The word \"well-formedd\" is invalid. The character '-' "
        "(U+2D) may not appear in the middle of a word."
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.add_to_personal_dictionary",
        lambda _word: AddToDictionaryResult(status="error", detail=detail),
    )
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage("well-formedd", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("d")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))
        await page.wait_for(lambda: bool(notifications))

        assert "well-formedd" in page.ta.app.misspelled_words()
        assert page.text == "well-formedd"
        assert notifications == [
            (f"Could not add 'well-formedd' to aspell: {detail}", "error")
        ]


async def test_spellcheck_dictionary_unavailable_notifies_warning_and_leaves_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="misspelled", suggestions=()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.add_to_personal_dictionary",
        lambda _word: AddToDictionaryResult(status="unavailable"),
    )
    notifications: list[tuple[str, str | None]] = []

    async with PromptPage("zzzzz word", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append((message, severity)),
        )
        await page.press("K")
        await page.wait_for(lambda: _top_is(page, SpellcheckPanelModal))
        await page.press("d")
        await page.wait_for(lambda: not _top_is(page, SpellcheckPanelModal))
        await page.wait_for(lambda: bool(notifications))

        assert "zzzzz" in page.ta.app.misspelled_words()
        assert page.text == "zzzzz word"
        assert notifications == [
            ("aspell is no longer available; 'zzzzz' was not added", "warning")
        ]


async def test_k_on_now_correct_remembered_word_forgets_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: SpellCheckResult(status="correct"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: DefinitionResult(status="no_match"),
    )
    notifications: list[str] = []

    async with PromptPage(
        "hello there",
        cursor=(0, 2),
        size=(80, 24),
        misspellings=["hello"],
    ) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append(message),
        )
        assert "hello" in page.ta.app.misspelled_words()

        await page.press("K")
        await page.wait_for(lambda: bool(notifications))

        assert "hello" not in page.ta.app.misspelled_words()


@pytest.mark.parametrize(
    "spelling",
    [
        SpellCheckResult(status="unavailable"),
        SpellCheckResult(status="error", detail="boom"),
    ],
)
async def test_unavailable_and_error_verdicts_record_nothing(
    monkeypatch: pytest.MonkeyPatch,
    spelling: SpellCheckResult,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.check_spelling",
        lambda _word: spelling,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets._prompt_word_lookup.look_up_definitions",
        lambda _word: DefinitionResult(status="unavailable"),
    )
    notifications: list[str] = []

    async with PromptPage("wrod there", cursor=(0, 2), size=(80, 24)) as page:
        monkeypatch.setattr(
            page.ta,
            "notify",
            lambda message, severity=None: notifications.append(message),
        )

        await page.press("K")
        await page.wait_for(lambda: bool(notifications))

        assert page.ta.app.misspelled_words() == frozenset()


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
                "Move the cursor onto an xprompt, skill, file path, glossary "
                "term, repo name, or word to look it up",
                "warning",
            )
        ]
        assert page.ta._prompt_preview_request_id == 0
