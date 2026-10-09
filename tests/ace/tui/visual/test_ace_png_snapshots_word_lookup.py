"""sase's TUI PNG visual snapshots for word lookup panels."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.spellcheck_panel_modal import SpellcheckPanelModal
from sase.ace.tui.modals.word_definition_card import build_definition_card
from sase.ace.tui.modals.word_definition_modal import WordDefinitionModal
from sase.core.word_lookup import _parse_definition_sections
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "dict"


def _card_for(word: str):
    raw = (_FIXTURES / f"{word}.txt").read_text()
    return build_definition_card(word, _parse_definition_sections(raw))


async def test_word_definition_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(WordDefinitionModal(_card_for("refuting")))
        await page.expect_modal("WordDefinitionModal")
        await wait_for_svg_contains(page, "To disprove and overthrow")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "word_definition_modal_120x40",
            title="ACE prompt word definition panel",
        )


async def test_word_definition_modal_wordnet_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(WordDefinitionModal(_card_for("ephemeral")))
        await page.expect_modal("WordDefinitionModal")
        await wait_for_svg_contains(page, "lasting a very short time")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "word_definition_modal_wordnet_120x40",
            title="ACE prompt word definition panel with WordNet lead",
        )


async def test_word_definition_modal_wordnet_light_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.theme = "textual-light"
        page.app.push_screen(WordDefinitionModal(_card_for("ephemeral")))
        await page.expect_modal("WordDefinitionModal")
        await wait_for_svg_contains(page, "lasting a very short time")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "word_definition_modal_wordnet_light_120x40",
            title="ACE prompt word definition panel with WordNet lead in light theme",
        )


async def test_word_definition_modal_long_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(WordDefinitionModal(_card_for("run")))
        await page.expect_modal("WordDefinitionModal")
        await wait_for_svg_contains(page, "DICTIONARY")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "word_definition_modal_long_70x24",
            title="ACE prompt word definition panel with long entry",
        )


async def test_spellcheck_panel_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    suggestions = (
        "accommodate",
        "accommodated",
        "accommodates",
        "accommodation",
        "accommodating",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(SpellcheckPanelModal("accomodate", suggestions))
        await page.expect_modal("SpellcheckPanelModal")
        await wait_for_svg_contains(page, "accommodation")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "spellcheck_panel_modal_120x40",
            title="ACE prompt spellcheck panel",
        )


async def test_spellcheck_panel_modal_full_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nine suggestions prove the ``max-height: 20`` bump renders the whole footer."""
    patch_startup_loaders(monkeypatch)
    suggestions = (
        "accommodate",
        "accommodated",
        "accommodates",
        "accommodation",
        "accommodating",
        "accommodative",
        "accommodator",
        "accommodators",
        "accommodatingly",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(SpellcheckPanelModal("accomodate", suggestions))
        await page.expect_modal("SpellcheckPanelModal")
        await wait_for_svg_contains(page, "add to aspell")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "spellcheck_panel_modal_full_120x40",
            title="ACE prompt spellcheck panel with nine suggestions",
        )


async def test_spellcheck_panel_modal_no_suggestions_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-line footer variant shown when ``aspell`` has no suggestions."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(SpellcheckPanelModal("zzzzz", ()))
        await page.expect_modal("SpellcheckPanelModal")
        await wait_for_svg_contains(page, "no suggestions")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "spellcheck_panel_modal_no_suggestions_120x40",
            title="ACE prompt spellcheck panel with no suggestions",
        )
