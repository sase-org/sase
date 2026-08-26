"""Regression tests for popup-panel tab switch keymaps."""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.modals import HelpModal
from sase.ace.tui.widgets import AxeOnboarding, PatchOnboarding


def _static_plain(modal: object, selector: str) -> str:
    widget = modal.query_one(selector, Static)  # type: ignore[attr-defined]
    content = widget.content
    return getattr(content, "plain", str(content))


def _help_title(page: AcePage) -> str:
    modal = page.app.screen_stack[-1]
    assert isinstance(modal, HelpModal)
    return _static_plain(modal, "#help-title")


def _guide_is(page: AcePage, guide_type: type[object]) -> bool:
    modal = page.app.screen_stack[-1]
    assert isinstance(modal, HelpModal)
    try:
        return isinstance(modal.query_one(guide_type), guide_type)
    except Exception:
        return False


async def test_help_modal_tab_switch_keys_change_tab_and_refresh_content() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        assert "Artifacts Tab" in _help_title(page)

        await page.press("tab")

        await page.expect_state("tab", "axe")
        await page.wait_for(lambda _state: "Axe Tab" in _help_title(page))

        await page.press("shift+tab")

        await page.expect_state("tab", "patches")
        await page.wait_for(lambda _state: "Artifacts Tab" in _help_title(page))


async def test_help_guide_tab_uses_configured_tab_switch_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"ace": {"keymaps": {"app": {"next_tab": "f2", "prev_tab": "f1"}}}},
    )
    monkeypatch.setattr(AceApp, "_schedule_axe_async_refresh", lambda self: None)

    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.press("question_mark")
        await page.expect_modal("HelpModal")
        await page.press("]")
        assert _guide_is(page, PatchOnboarding)

        await page.press("f2")

        await page.expect_state("tab", "axe")
        await page.wait_for(lambda _state: _guide_is(page, AxeOnboarding))

        await page.press("f1")

        await page.expect_state("tab", "patches")
        await page.wait_for(lambda _state: _guide_is(page, PatchOnboarding))
