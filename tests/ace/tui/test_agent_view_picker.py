"""Mounted-app coverage for the Agents view picker route."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.commands import build_command_catalog
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry
from sase.ace.tui.modals.agent_view_modal import AgentViewModal
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets._agent_detail_panels import (
    DetailLayoutMode,
    DetailPanelMode,
)
from tests.ace.tui._agents_zoom_panel_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


async def test_agents_p_opens_picker_and_direct_mode_choice_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_make_agent()])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await page.press("p")
        await page.expect_modal("AgentViewModal")
        first_screen = page.app.screen
        assert isinstance(first_screen, AgentViewModal)
        llm_calls_choice = first_screen.choices[1]
        assert llm_calls_choice.key == "t"
        assert llm_calls_choice.label == "LLM Calls"
        assert llm_calls_choice.subtitle == "Provider tool calls and activity"

        await page.press("]")
        await page.pause()
        assert page.app.screen is first_screen

        await page.press("0")
        await page.expect_no_modal()

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        assert detail.panel_mode is DetailPanelMode.INFO


async def test_agents_brackets_are_inert_on_agents_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_make_agent()])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        before = detail.panel_mode

        await page.press("right_square_bracket", "left_square_bracket")
        await page.pause()

        assert detail.panel_mode is before
        assert not isinstance(page.app.screen, AgentViewModal)


async def test_agents_pp_cycles_visible_file_layout_next(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Notes\n\nready\n")
    patch_startup_loaders(
        monkeypatch,
        agents=[_make_agent(status="DONE", extra_files=[str(file_path)])],
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(
            lambda _screen: (
                detail.panel_mode is DetailPanelMode.AUTO
                and detail.is_file_visible()
                and detail._has_file_content
            )
        )
        detail.set_detail_layout(DetailLayoutMode.SECONDARY_LARGER)

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        modal = page.app.screen
        assert isinstance(modal, AgentViewModal)
        assert not modal.query_one("#agent-view-row-6").has_class("disabled")
        await page.press("p")
        await page.expect_no_modal()

        assert detail.detail_layout_mode is DetailLayoutMode.METADATA_LARGER


async def test_agents_p_upper_p_cycles_visible_file_layout_previous(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Notes\n\nready\n")
    patch_startup_loaders(
        monkeypatch,
        agents=[_make_agent(status="DONE", extra_files=[str(file_path)])],
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(
            lambda _screen: (
                detail.panel_mode is DetailPanelMode.AUTO
                and detail.is_file_visible()
                and detail._has_file_content
            )
        )
        detail.set_detail_layout(DetailLayoutMode.SECONDARY_LARGER)

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        await page.press("P")
        await page.expect_no_modal()

        assert detail.detail_layout_mode is DetailLayoutMode.EQUAL


async def test_agents_picker_direct_layout_choices_apply_all_three(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Notes\n\nready\n")
    patch_startup_loaders(
        monkeypatch,
        agents=[_make_agent(status="DONE", extra_files=[str(file_path)])],
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(
            lambda _screen: (
                detail.panel_mode is DetailPanelMode.AUTO
                and detail.is_file_visible()
                and detail._has_file_content
            )
        )

        for key, expected in (
            ("1", DetailLayoutMode.METADATA_LARGER),
            ("=", DetailLayoutMode.EQUAL),
            ("2", DetailLayoutMode.SECONDARY_LARGER),
        ):
            await page.press("p")
            await page.expect_modal("AgentViewModal")
            await page.press(key)
            await page.expect_no_modal()
            assert detail.detail_layout_mode is expected


async def test_agents_equal_layout_survives_view_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.md"
    file_path.write_text("# Notes\n\nready\n")
    patch_startup_loaders(
        monkeypatch,
        agents=[_make_agent(status="DONE", extra_files=[str(file_path)])],
    )

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        await page.wait_for(
            lambda _screen: (
                detail.panel_mode is DetailPanelMode.AUTO
                and detail.is_file_visible()
                and detail._has_file_content
            )
        )

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        await page.press("=")
        await page.expect_no_modal()
        assert detail.detail_layout_mode is DetailLayoutMode.EQUAL

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        await page.press("0")
        await page.expect_no_modal()
        assert detail.panel_mode is DetailPanelMode.INFO
        assert detail.detail_layout_mode is DetailLayoutMode.EQUAL

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        await page.press("t")
        await page.expect_no_modal()
        assert detail.panel_mode is DetailPanelMode.LLM_CALLS
        assert detail.detail_layout_mode is DetailLayoutMode.EQUAL

        await page.press("p")
        await page.expect_modal("AgentViewModal")
        await page.press("f")
        await page.expect_no_modal()
        assert detail.panel_mode is DetailPanelMode.AUTO
        assert detail.detail_layout_mode is DetailLayoutMode.EQUAL


def test_agent_view_keymap_catalog_and_retired_overrides() -> None:
    registry = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "toggle_layout": "f1",
                    "toggle_thinking": "f2",
                    "toggle_thinking_reverse": "f3",
                }
            }
        }
    )
    assert registry.app.choose_agent_view == "p"

    bindings = build_app_bindings(registry.app)
    assert any(binding.action == "choose_agent_view" for binding in bindings)
    assert not any(binding.action == "toggle_layout" for binding in bindings)
    assert not any(binding.action == "toggle_thinking" for binding in bindings)
    assert not any(binding.action == "toggle_thinking_reverse" for binding in bindings)

    catalog_ids = {spec.id for spec in build_command_catalog(registry)}
    assert "app.choose_agent_view" in catalog_ids
    assert "app.toggle_layout" not in catalog_ids
    assert "app.toggle_thinking" not in catalog_ids
    assert "app.toggle_thinking_reverse" not in catalog_ids
