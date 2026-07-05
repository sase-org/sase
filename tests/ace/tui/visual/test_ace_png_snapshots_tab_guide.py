"""ACE TUI PNG visual snapshot coverage for the Tab Guide modal."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import TabGuideModal
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    axe_collected_data,
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_tab_guide_axe_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The AXE tab's on-demand guide is the flagship new guide content."""
    patch_startup_loaders(monkeypatch, axe_data=axe_collected_data())

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("tab")
        await page.expect_state("tab", "axe")

        page.app.push_screen(
            TabGuideModal(current_tab="axe", registry=page.app._keymap_registry)
        )
        await page.expect_modal("TabGuideModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Automation, always on")
        assert_page_svg_contains(page, "Background commands")
        assert_page_svg_contains(page, "https://sase.sh/axe/")
        assert_page_svg_contains(page, "https://sase.sh/workflow_spec/")
        ace_png_visual.assert_page_png(
            page,
            "tab_guide_axe_120x40",
            title="ACE tab guide modal (AXE)",
        )


async def test_tab_guide_agents_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The modal reuses Agents onboarding content with modal-specific footer."""
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")

        page.app.push_screen(
            TabGuideModal(
                current_tab="agents",
                registry=page.app._keymap_registry,
                agents_launch_targets_available=True,
                agents_plugins_installed=True,
            )
        )
        await page.expect_modal("TabGuideModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Welcome to sase ace")
        assert_page_svg_contains(page, "esc closes")
        assert_page_svg_contains(page, "https://sase.sh/ace/")
        assert_page_svg_contains(page, "https://sase.sh/xprompt/")
        ace_png_visual.assert_page_png(
            page,
            "tab_guide_agents_120x40",
            title="ACE tab guide modal (Agents)",
        )
