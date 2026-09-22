"""Xprompt-properties tests for the prompt preview modal."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Input, Markdown, Static

from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from tests.ace.tui.modals.preview_panel_modal_test_helpers import (
    _PreviewModalTestApp,
    _payload,
    _properties_payload,
    _wait_for_modal_state,
)


async def test_preview_modal_shows_properties_band_only_when_declared() -> None:
    app = _PreviewModalTestApp(_properties_payload())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal.query_one("#preview-properties", Static).display is True

    app_without = _PreviewModalTestApp(_payload())
    async with app_without.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app_without.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        assert modal.query_one("#preview-properties", Static).display is False


async def test_preview_modal_p_opens_and_restores_properties_view() -> None:
    app = _PreviewModalTestApp(_properties_payload())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        await pilot.press("p")
        await pilot.pause()

        assert modal._view_mode == "properties"  # noqa: SLF001
        assert modal.query_one("#preview-properties-view", Static).display is True
        assert modal.query_one("#preview-content", Static).display is False
        assert modal.query_one("#preview-properties", Static).display is False
        title = modal.query_one("#preview-title", Static)
        assert "PROPERTIES" in title.render().plain

        await pilot.press("p")
        await pilot.pause()

        assert modal._view_mode == "source"  # noqa: SLF001
        assert modal.query_one("#preview-content", Static).display is True
        assert modal.query_one("#preview-properties-view", Static).display is False
        assert modal.query_one("#preview-properties", Static).display is True


async def test_preview_modal_p_restores_rendered_mode_when_that_was_active() -> None:
    app = _PreviewModalTestApp(_properties_payload(default_view="rendered"))

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        await _wait_for_modal_state(
            pilot,
            lambda: modal._view_mode == "rendered",  # noqa: SLF001
        )

        await pilot.press("p")
        await pilot.pause()
        assert modal._view_mode == "properties"  # noqa: SLF001

        await pilot.press("p")
        await pilot.pause()
        assert modal._view_mode == "rendered"  # noqa: SLF001
        assert modal.query_one("#preview-rendered", Markdown).display is True
        assert modal.query_one("#preview-properties-view", Static).display is False


async def test_preview_modal_p_warns_when_no_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []
    app = _PreviewModalTestApp(_payload())

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        await pilot.press("p")
        await pilot.pause()

        assert modal._view_mode == "source"  # noqa: SLF001

    assert notifications == [("This preview has no xprompt properties", "warning")]


def test_preview_modal_footer_includes_properties_chip_only_when_declared() -> None:
    modal = PreviewPanelModal(_properties_payload())
    assert "p properties" in modal._build_footer()  # noqa: SLF001

    modal_without = PreviewPanelModal(_payload())
    assert "p properties" not in modal_without._build_footer()  # noqa: SLF001


async def test_preview_modal_search_switches_properties_view_to_source() -> None:
    app = _PreviewModalTestApp(_properties_payload())

    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        await pilot.press("p")
        await pilot.pause()
        assert modal._view_mode == "properties"  # noqa: SLF001

        await pilot.press("/")

        assert modal._view_mode == "source"  # noqa: SLF001
        assert modal.query_one("#preview-search-input", Input).display is True
