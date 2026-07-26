"""Opening and initializing the unified xprompt/snippet save panel."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.modals import UnifiedSaveLocation, UnifiedXPromptSaveModal
from sase.ace.tui.modals.xprompt_location_modal import XPromptLocation
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.models import InputArg, InputType

from ._prompt_save_xprompt_helpers import (
    _SaveFlowApp,
    _SaveHarness,
    _wait_save_tasks,
)


async def test_empty_save_request_toasts_noop() -> None:
    harness = _SaveHarness()
    await harness.on_prompt_input_bar_save_as_xprompt_requested(
        PromptInputBar.SaveAsXpromptRequested([])
    )
    await _wait_save_tasks(harness)
    assert harness.notifications == [("Nothing to save as an xprompt", "warning")]
    assert harness.pushed == []


async def test_request_opens_one_screen_with_active_pane_snippet_source() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(text="alpha", frontmatter=""),
                    StashedPromptPane(text="beta", frontmatter=""),
                ],
                snippet_body="beta",
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "alpha\n---\nbeta"
    assert modal._snippet_body == "beta"
    assert modal._pane_count == 2


async def test_request_converts_placeholders_for_xprompt_preview_only() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [
                    StashedPromptPane(
                        text="Deploy <service> to <target file>",
                        frontmatter=(
                            "---\n"
                            "input:\n"
                            "  service:\n"
                            "    type: path\n"
                            "    default: api\n"
                            "---"
                        ),
                    )
                ],
                snippet_body="Deploy <service> to <target file>",
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "Deploy {{ service }} to {{ target_file }}"
    assert modal._snippet_body == "Deploy <service> to <target file>"
    service = modal._frontmatter.get_input("service")
    assert service is not None
    assert service.type is InputType.PATH
    assert service.default == "api"
    target = modal._frontmatter.get_input("target_file")
    assert target == InputArg(name="target_file", type=InputType.TEXT)


async def test_request_reuses_undeclared_jinja_name_without_duplicate_input() -> None:
    harness = _SaveHarness()
    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        await harness.on_prompt_input_bar_save_as_xprompt_requested(
            PromptInputBar.SaveAsXpromptRequested(
                [StashedPromptPane(text="Deploy <service> with {{ service }}")]
            )
        )
        await _wait_save_tasks(harness)

    modal, _callback = harness.pushed[0]
    assert isinstance(modal, UnifiedXPromptSaveModal)
    assert modal._body == "Deploy {{ service }} with {{ service }}"
    assert modal._frontmatter.inputs == []


async def test_ctrl_g_ctrl_x_ctrl_x_opens_panel_in_snippet_mode(
    tmp_path: Path,
) -> None:
    xprompt_directory = tmp_path / "xprompts"
    xprompt_directory.mkdir()
    snippet_config = tmp_path / "sase.yml"
    snippet_config.write_text("ace:\n  snippets: {}\n", encoding="utf-8")
    xprompt_location = UnifiedSaveLocation(
        location=XPromptLocation("Xprompts", str(xprompt_directory), "directory"),
        group="CWD directories",
        display_path=str(xprompt_directory),
        names=frozenset(),
    )
    snippet_location = UnifiedSaveLocation(
        location=XPromptLocation("Snippets", str(snippet_config), "config"),
        group="Config files",
        display_path=str(snippet_config),
        names=frozenset(),
    )
    app = _SaveFlowApp("draft to reuse")

    with (
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
            return_value=[xprompt_location],
        ),
        patch(
            "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
            return_value=[snippet_location],
        ),
        patch("sase.xprompt.save_state.load_last_used_locations", return_value={}),
    ):
        async with app.run_test(size=(105, 36)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            text_area = bar.active_text_area()

            await pilot.press("ctrl+g", "ctrl+x")
            for _ in range(20):
                await pilot.pause()
                if isinstance(app.screen, UnifiedXPromptSaveModal):
                    break

            modal = app.screen
            assert isinstance(modal, UnifiedXPromptSaveModal)
            assert len(app.save_requests) == 1
            assert bar.all_prompt_texts() == ["draft to reuse"]
            assert text_area._insert_g_prefix_pending is False
            assert bar._g_prefix_hints_visible is False

            await pilot.press("ctrl+x")
            assert modal._mode == "snippet"
            assert bar.all_prompt_texts() == ["draft to reuse"]

    # Opening and toggling the deterministic panel never writes either target.
    assert list(xprompt_directory.iterdir()) == []
    assert snippet_config.read_text(encoding="utf-8") == "ace:\n  snippets: {}\n"


async def test_save_request_returns_while_location_reads_are_stuck() -> None:
    harness = _SaveHarness()
    entered = threading.Event()
    release = threading.Event()

    def _slow_locations(*_args: object) -> list[object]:
        entered.set()
        release.wait(timeout=1.0)
        return []

    def _slow_last_used() -> dict[str, str]:
        entered.set()
        release.wait(timeout=1.0)
        return {}

    try:
        with (
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_save_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.ace.tui.modals.unified_xprompt_save_modal.load_unified_snippet_locations",
                side_effect=_slow_locations,
            ),
            patch(
                "sase.xprompt.save_state.load_last_used_locations",
                side_effect=_slow_last_used,
            ),
        ):
            await asyncio.wait_for(
                harness.on_prompt_input_bar_save_as_xprompt_requested(
                    PromptInputBar.SaveAsXpromptRequested(
                        [StashedPromptPane(text="draft")]
                    )
                ),
                timeout=0.05,
            )
            await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)
            heartbeat = asyncio.Event()
            asyncio.get_running_loop().call_soon(heartbeat.set)
            await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
    finally:
        release.set()
        await _wait_save_tasks(harness)
