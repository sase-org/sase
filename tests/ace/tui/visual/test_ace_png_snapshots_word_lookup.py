"""ACE TUI PNG visual snapshots for word lookup panels."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.spellcheck_panel_modal import SpellcheckPanelModal
from sase.ace.tui.modals.word_definition_modal import WordDefinitionModal
from sase.core.word_lookup import DefinitionSection
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_word_definition_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    sections = (
        DefinitionSection(
            source="The Collaborative International Dictionary",
            body=(
                "  serendipity \\ser-en-DIP-i-tee\\, noun\n\n"
                "      The faculty of making fortunate discoveries by accident.\n"
                "      A pleasant discovery made while looking for something else."
            ),
        ),
        DefinitionSection(
            source="WordNet (r) 3.1",
            body=(
                "  serendipity\n"
                "      n 1: accidental sagacity; the faculty of making fortunate\n"
                "           discoveries of things you were not looking for"
            ),
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(WordDefinitionModal("serendipity", sections))
        await page.expect_modal("WordDefinitionModal")
        await wait_for_svg_contains(page, "fortunate discoveries")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "word_definition_modal_120x40",
            title="ACE prompt word definition panel",
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
        await page.press("2")
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
        await page.press("2")
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
        await page.press("2")
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
