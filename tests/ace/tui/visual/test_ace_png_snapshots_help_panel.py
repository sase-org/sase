"""ACE TUI PNG visual snapshot coverage for the Help panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import HelpModal
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    axe_collected_data,
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _open_help_guide(page: AcePage, modal: HelpModal) -> None:
    page.app.push_screen(modal)
    await page.expect_modal("HelpModal")
    await page.press("]")
    await wait_for_visual_idle(page)


async def test_help_panel_keymaps_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Help panel opens to the keymap reference first."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        page.app.push_screen(
            HelpModal(
                current_tab="patches",
                active_query=page.app.canonical_query_string,
                registry=page.app._keymap_registry,
            )
        )
        await page.expect_modal("HelpModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "sase ace Help")
        assert_page_svg_contains(page, "Keymaps")
        assert_page_svg_contains(page, "Guide")
        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "help_keymaps_changespecs_120x40",
            title="ACE Help panel keymaps (PRs)",
        )


async def test_help_panel_filter_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typing into the `/` filter bar narrows the Keymaps view live."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        modal = HelpModal(
            current_tab="patches",
            active_query=page.app.canonical_query_string,
            registry=page.app._keymap_registry,
        )
        page.app.push_screen(modal)
        await page.expect_modal("HelpModal")
        await wait_for_visual_idle(page)

        modal.action_focus_filter()
        await page.press("b", "e", "a", "d")
        await page.wait_for(lambda _s: modal._filter_query == "bead")
        await wait_for_visual_idle(page)

        # "Bead" renders as its own highlighted span (the matched run), so it
        # stays contiguous in the exported SVG even though "Bead Pane" as a
        # whole does not.
        assert_page_svg_contains(page, "Bead")
        assert_page_svg_contains(page, "Pane")
        ace_png_visual.assert_page_png(
            page,
            "help_keymaps_filter_120x40",
            title="ACE Help panel keymaps filter (bead)",
        )


async def test_help_guide_axe_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AXE guide is available inside the Help panel's Guide tab."""
    patch_startup_loaders(monkeypatch, axe_data=axe_collected_data())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.press("tab")
        await page.expect_state("tab", "axe")

        await _open_help_guide(
            page,
            HelpModal(
                current_tab="axe",
                active_query=page.app.canonical_query_string,
                registry=page.app._keymap_registry,
            ),
        )

        assert_page_svg_contains(page, "Automation, always on")
        assert_page_svg_contains(page, "Axe starts automatically")
        assert_page_svg_contains(page, "with the Axe row selected")
        ace_png_visual.assert_page_png(
            page,
            "help_guide_axe_120x40",
            title="ACE Help panel guide (AXE)",
        )


async def test_help_guide_agents_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Help panel reuses Agents onboarding content without internal footer."""
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        await _open_help_guide(
            page,
            HelpModal(
                current_tab="agents",
                active_query=page.app.canonical_query_string,
                registry=page.app._keymap_registry,
                agents_launch_targets_available=True,
                agents_plugins_installed=True,
            ),
        )

        assert_page_svg_contains(page, "Welcome to sase ace")
        assert_page_svg_contains(page, "? / q / esc close")
        assert_page_svg_contains(page, "Read what happened")
        ace_png_visual.assert_page_png(
            page,
            "help_guide_agents_120x40",
            title="ACE Help panel guide (Agents)",
        )


async def test_help_guide_patches_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Artifacts guide remains available inside the Help panel's Guide tab."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        await _open_help_guide(
            page,
            HelpModal(
                current_tab="patches",
                active_query=page.app.canonical_query_string,
                registry=page.app._keymap_registry,
            ),
        )

        assert_page_svg_contains(page, "Everything your agents produce")
        assert_page_svg_contains(page, "Know what each view shows")
        ace_png_visual.assert_page_png(
            page,
            # legacy compatibility retained PNG filename
            "help_guide_changespecs_120x40",
            title="ACE Help panel guide (Artifacts)",
        )
