"""ACE TUI PNG visual snapshot for the empty Agents-tab onboarding view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents import _onboarding_launch_targets
from sase.ace.tui.actions.agents import _onboarding_plugins
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _wait_for_onboarding_plugins_refresh(
    page: AcePage,
    calls: list[bool],
) -> None:
    await wait_for_state(
        page,
        lambda: (
            bool(calls)
            and not page.app._agents_onboarding_plugins_refresh_scheduled
            and not page.app._agents_onboarding_plugins_refresh_running
        ),
        description="Agents onboarding plugin discovery to finish",
    )


async def test_agents_onboarding_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_calls: list[bool] = []

    def _plugins_installed() -> bool:
        plugin_calls.append(True)
        return True

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_launch_targets,
        "discover_agents_onboarding_launch_targets_available",
        lambda: False,
    )
    monkeypatch.setattr(
        _onboarding_plugins,
        "discover_agents_onboarding_plugins_installed",
        _plugins_installed,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_plugins_refresh(page, plugin_calls)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Every agent you launch")
        assert_page_svg_contains(page, "SASE Admin Center")
        assert_page_svg_contains(page, "The full tour of this tab")
        assert "pick a project or PR first." not in page.screen
        ace_png_visual.assert_page_png(
            page,
            "agents_onboarding_120x40",
            title="ACE agents onboarding",
        )


async def test_agents_onboarding_no_plugins_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_calls: list[bool] = []

    def _no_plugins_installed() -> bool:
        plugin_calls.append(True)
        return False

    patch_startup_loaders(monkeypatch, agents=[])
    monkeypatch.setattr(
        _onboarding_launch_targets,
        "discover_agents_onboarding_launch_targets_available",
        lambda: False,
    )
    monkeypatch.setattr(
        _onboarding_plugins,
        "discover_agents_onboarding_plugins_installed",
        _no_plugins_installed,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 0)
        await _wait_for_onboarding_plugins_refresh(page, plugin_calls)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Every agent you launch")
        assert_page_svg_contains(page, "SASE Admin Center")
        assert "sase-github" not in page.screen
        ace_png_visual.assert_page_png(
            page,
            "agents_onboarding_no_plugins_120x40",
            title="ACE agents onboarding without plugins",
        )
