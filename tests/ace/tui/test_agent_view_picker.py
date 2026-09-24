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
from sase.ace.tui.widgets.llm_calls_panel import LLMCallsVisibilityChanged
from tests.ace.tui._agents_zoom_panel_helpers import _make_agent
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


def _secondary_scrolls_hidden(detail: AgentDetail) -> bool:
    file_scroll = detail.query_one("#agent-file-scroll")
    llm_calls_scroll = detail.query_one("#agent-llm-calls-scroll")
    return file_scroll.has_class("hidden") and llm_calls_scroll.has_class("hidden")


async def _wait_for_file_availability(page: AcePage, detail: AgentDetail) -> None:
    await page.wait_for(
        lambda _screen: (
            detail.panel_mode is DetailPanelMode.AUTO and detail._has_file_content
        )
    )


async def test_agents_brackets_are_inert_on_agents_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_make_agent()])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        before = detail.panel_mode
        before_layout = detail.detail_layout_mode

        await page.press("right_square_bracket", "left_square_bracket")
        await page.pause()

        assert detail.panel_mode is before
        assert detail.detail_layout_mode is before_layout
        assert not isinstance(page.app.screen, AgentViewModal)


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
