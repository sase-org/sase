"""Modal behavior coverage for the registry-driven Copy as palette."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from sase.ace.tui.modals.copy_as_types import CopyAsRow
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets import KeybindingFooter
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from tests.ace.tui._copy_as_palette_helpers import (
    CopyAsModalApp,
    copy_as_row,
    modal_context,
)


@pytest.mark.parametrize(
    ("key", "target"), [("q", "raw"), ("j", "spec"), ("k", "snapshot")]
)
async def test_configured_accelerators_win_over_modal_navigation(
    key: str,
    target: str,
) -> None:
    context = modal_context(
        copy_as_row("q", "raw", category="Content"),
        copy_as_row("j", "spec", category="Content"),
        copy_as_row("k", "snapshot", category="Actions"),
    )
    app = CopyAsModalApp(context)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press(key)
        await pilot.pause()

    assert app.results == [next(row for row in context.rows if row.target == target)]


async def test_modal_navigation_enter_unknown_and_cancel_behavior() -> None:
    first = copy_as_row("x", "name")
    second = copy_as_row("y", "raw", category="Content")
    app = CopyAsModalApp(modal_context(first, second))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("z")
        assert isinstance(app.screen_stack[-1], CopyAsModal)
        assert app.messages == [("Unknown copy key (Patches: x, y)", "warning")]

        await pilot.press("j", "enter")
        await pilot.pause()

    assert app.results == [second]


async def test_disabled_accelerator_explains_reason_and_keeps_palette_open() -> None:
    row = CopyAsRow(
        key="c",
        key_display="c",
        target="contents",
        label="Copy contents",
        category="Content",
        preview="unavailable",
        disabled_reason="Contents copy is unavailable",
    )
    app = CopyAsModalApp(modal_context(row))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("c")

        assert isinstance(app.screen_stack[-1], CopyAsModal)
        assert app.messages == [("Contents copy is unavailable", "warning")]

        await pilot.press("escape")
        await pilot.pause()

    assert app.results == [None]


async def test_modal_mouse_selection_dispatches_highlighted_row() -> None:
    first = copy_as_row("x", "name")
    app = CopyAsModalApp(modal_context(first))

    async with app.run_test(size=(80, 24)) as pilot:
        modal = app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        option_list = modal.query_one("#copy-as-list")
        await pilot.click(option_list, offset=(2, 2))
        await pilot.pause()

    assert app.results == [first]


async def test_q_and_escape_cancel_when_not_configured() -> None:
    for key in ("q", "escape"):
        app = CopyAsModalApp(modal_context(copy_as_row("x", "name")))
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press(key)
            await pilot.pause()
        assert app.results == [None]


async def test_pr_palette_dispatch_and_lifecycle_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        copy_name = MagicMock()
        monkeypatch.setattr(page.app, "_copy_cl_name", copy_name)

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        assert page.app._copy_mode_active is True

        await page.press("n")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        copy_name.assert_called_once_with()
        assert page.app._copy_mode_active is False

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("enter")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

        assert copy_name.call_count == 2


async def test_real_escape_and_q_restore_normal_footer() -> None:
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        footer = page.query_one_widget("#keybinding-footer", KeybindingFooter)

        for key in ("escape", "q"):
            await page.press("%")
            await page.expect_modal("CopyAsModal")
            assert footer._last_layout_inputs is not None
            assert footer._last_layout_inputs[1] == "COPY"

            await page.press(key)
            await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)

            assert page.app._copy_mode_active is False
            assert footer._last_layout_inputs is not None
            assert footer._last_layout_inputs[1] is None


async def test_snapshot_dispatch_waits_until_palette_is_unmounted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_frames: list[tuple[str, bool]] = []
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        monkeypatch.setattr(
            page.app,
            "_copy_snapshot",
            lambda: captured_frames.append(
                (
                    type(page.app.screen_stack[-1]).__name__,
                    "Copy as" in page.screen,
                )
            ),
        )

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("s")
        await page.wait_for(lambda _state: len(page.app.screen_stack) == 1)
        await page.pause()

    assert captured_frames == [("Screen", False)]


async def test_unknown_key_retains_real_palette_and_copy_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[tuple[str, str]] = []
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kwargs: messages.append(
                (message, severity)
            ),
        )

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        await page.press("x")

        assert isinstance(page.app.screen_stack[-1], CopyAsModal)
        assert page.app._copy_mode_active is True
        assert messages[-1][0].startswith("Unknown copy key (Patches:")


async def test_copy_palette_stacks_over_forwarding_modal() -> None:
    payload = PreviewPayload(
        kind_label="file",
        icon="@",
        title="copy_as_palette.md",
        source_path="/workspace/copy_as_palette.md",
        lexer="markdown",
        content="# Copy as palette",
    )
    async with AcePage() as page:
        page.app.current_artifacts_subtab = "prs"
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")

        await page.press("%")
        await page.expect_modal("CopyAsModal")
        assert isinstance(page.app.screen_stack[-2], PreviewPanelModal)

        await page.press("escape")
        await page.expect_modal("PreviewPanelModal")
        assert page.app._copy_mode_active is False
