"""Tests for the StartupSplashScreen modal screen behaviour."""

from __future__ import annotations

import asyncio

import pytest
from textual.screen import ModalScreen

from sase.ace.testing import AcePage
from sase.ace.tui.modals.startup_splash import StartupSplashScreen


async def _wait_real(page: AcePage, seconds: float) -> None:
    """Advance real time and then let the Textual message pump catch up.

    ``asyncio.sleep`` alone advances Textual's monotonic-clock timers, and
    ``pilot.pause()`` afterwards drains the resulting messages.
    """
    await asyncio.sleep(seconds)
    await page._pilot.pause()


@pytest.mark.asyncio
async def test_splash_on_top_after_mount() -> None:
    """When ``skip_splash=False`` the splash screen is the active screen."""
    async with AcePage(skip_splash=False) as page:
        assert isinstance(page.app.screen, StartupSplashScreen)
        assert isinstance(page.app.screen, ModalScreen)


@pytest.mark.asyncio
async def test_splash_dismisses_after_all_milestones_ready() -> None:
    """Once all three mark-* calls fire the splash removes itself."""
    async with AcePage(skip_splash=False) as page:
        splash = page.app.screen
        assert isinstance(splash, StartupSplashScreen)
        splash.mark_changespecs_ready()
        splash.mark_agents_ready()
        splash.mark_axe_ready()
        # Freeze fires after MINIMUM_DISPLAY_SECONDS; auto-dismiss fires
        # FREEZE_HOLD_SECONDS after that. Both timers need multiple event
        # loop ticks to fully land.
        for _ in range(5):
            await _wait_real(page, 0.6)
            if not isinstance(page.app.screen, StartupSplashScreen):
                break
        assert not isinstance(page.app.screen, StartupSplashScreen)


@pytest.mark.asyncio
async def test_splash_mark_changespecs_flips_first_milestone() -> None:
    """After ``mark_changespecs_ready`` the first milestone renders ``✓``."""
    async with AcePage(skip_splash=False) as page:
        splash = page.app.screen
        assert isinstance(splash, StartupSplashScreen)
        splash.mark_changespecs_ready()
        text = splash._build_milestones().plain
        first_line = text.split("\n")[0]
        assert "✓" in first_line
        assert "ChangeSpecs" in first_line


@pytest.mark.asyncio
async def test_splash_skip_key_dismisses_early() -> None:
    """Pressing Escape dismisses the splash even if milestones are pending."""
    async with AcePage(skip_splash=False) as page:
        splash = page.app.screen
        assert isinstance(splash, StartupSplashScreen)
        await page.press("escape")
        for _ in range(5):
            await _wait_real(page, 0.1)
            if not isinstance(page.app.screen, StartupSplashScreen):
                break
        assert not isinstance(page.app.screen, StartupSplashScreen)


@pytest.mark.asyncio
async def test_splash_suppressed_by_default_in_acepage() -> None:
    """The default AcePage path does not push the splash."""
    async with AcePage() as page:
        assert not isinstance(page.app.screen, StartupSplashScreen)
