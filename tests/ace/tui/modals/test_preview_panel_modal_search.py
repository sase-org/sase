"""Search and copy-mode tests for the prompt preview modal."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.util.lazy_syntax import PLAIN_RENDER_MAX_LINES
from tests.ace.tui.modals.preview_panel_modal_test_helpers import (
    _PreviewModalTestApp,
    _markdown_payload,
    _payload,
    _wait_for_modal_state,
)


async def test_preview_modal_forwards_percent_to_app_copy_mode() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "patches"
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(PreviewPanelModal(_payload()))
        await page.expect_modal("PreviewPanelModal")

        await page.press("%")

        await page.expect_modal("CopyAsModal")
        assert page.app._copy_mode_active is True
        assert isinstance(page.app.screen_stack[-2], PreviewPanelModal)


async def test_preview_modal_search_input_accepts_percent_as_query_text() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "files"
        page.app.current_files_subtab = "chats"
        await page.expect_state("files_subtab", "chats")
        modal = PreviewPanelModal(_payload())
        page.app.push_screen(modal)
        await page.expect_modal("PreviewPanelModal")

        await page.press("/")
        await page.press("%")

        assert page.app._copy_mode_active is False
        assert modal.query_one("#preview-search-input", Input).value == "%"


async def test_preview_modal_search_highlights_navigates_and_wraps() -> None:
    payload = replace(
        _payload(),
        content="zero\nNeedle one\nmiddle\nneedle two\nlast",
        lexer="text",
    )
    app = _PreviewModalTestApp(payload)

    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        await pilot.press("/")
        search_input = modal.query_one("#preview-search-input", Input)
        assert search_input.display is True
        await pilot.press("n", "e", "e", "d", "l", "e", "enter")
        await _wait_for_modal_state(
            pilot,
            lambda: modal._match_lines == (2, 4),  # noqa: SLF001
        )

        assert search_input.display is False
        assert modal._match_index == 0  # noqa: SLF001
        assert "1/2 · line 2" in modal._build_footer()  # noqa: SLF001
        renderable = modal._build_content()  # noqa: SLF001
        assert renderable.renderable.highlight_lines == {2, 4}

        await pilot.press("n")
        assert modal._match_index == 1  # noqa: SLF001
        assert "2/2 · line 4" in modal._build_footer()  # noqa: SLF001
        await pilot.press("n")
        assert modal._match_index == 0  # noqa: SLF001
        await pilot.press("N")
        assert modal._match_index == 1  # noqa: SLF001


async def test_preview_modal_search_escape_ladder_and_input_cancel() -> None:
    app = _PreviewModalTestApp(replace(_payload(), content="alpha\nbeta\nalpha"))

    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)

        await pilot.press("/", "b", "e", "t", "a", "escape")
        search_input = modal.query_one("#preview-search-input", Input)
        assert search_input.display is False
        assert modal._search_query == ""  # noqa: SLF001

        await pilot.press("/", "a", "l", "p", "h", "a", "enter")
        await _wait_for_modal_state(
            pilot,
            lambda: modal._match_lines == (1, 3),  # noqa: SLF001
        )
        await pilot.press("escape")
        assert modal._search_query == ""  # noqa: SLF001
        assert isinstance(app.screen_stack[-1], PreviewPanelModal)

        await pilot.press("escape")
        assert not isinstance(app.screen_stack[-1], PreviewPanelModal)


async def test_preview_modal_search_switches_rendered_markdown_to_source() -> None:
    app = _PreviewModalTestApp(_markdown_payload(default_view="rendered"))

    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        await _wait_for_modal_state(
            pilot,
            lambda: modal._view_mode == "rendered",  # noqa: SLF001
        )

        await pilot.press("/")

        assert modal._view_mode == "source"  # noqa: SLF001
        assert modal.query_one("#preview-search-input", Input).display is True


async def test_preview_modal_search_warns_for_match_beyond_display_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notifications: list[tuple[str, str]] = []
    content = "\n".join(["visible"] * PLAIN_RENDER_MAX_LINES + ["hidden target"])
    app = _PreviewModalTestApp(replace(_payload(), content=content, lexer="text"))

    def notify(
        message: str,
        *,
        severity: str = "information",
        **_kwargs: Any,
    ) -> None:
        notifications.append((message, severity))

    monkeypatch.setattr(app, "notify", notify)
    async with app.run_test(size=(70, 20)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, PreviewPanelModal)
        await pilot.press("/", "t", "a", "r", "g", "e", "t", "enter")
        await _wait_for_modal_state(
            pilot,
            lambda: modal._match_lines == (PLAIN_RENDER_MAX_LINES + 1,),  # noqa: SLF001
        )

    assert notifications == [
        (
            f"Match at line {PLAIN_RENDER_MAX_LINES + 1} "
            "is beyond the displayed portion",
            "warning",
        )
    ]
