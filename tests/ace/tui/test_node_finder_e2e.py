"""End-to-end wiring coverage for the Agents-tab Node Finder (``"`` key)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.testing import AcePage
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent import Agent, AgentType
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)


def _clan_member(name: str, suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="finder-clan",
        project_file="/tmp/projects/demo/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 19, 8, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        tribe=None,
        agent_clan="finder-clan",
        agent_clan_generation="finder-generation",
    )


def _allow(app: Any) -> bool:
    return check_app_action(app, "jump_to_node", (), lambda _a, _p: True) or False


def _available_app(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "current_tab": "agents",
        "_prompt_input_active": lambda: False,
        "_screen_stack": ("home",),
        "screen": SimpleNamespace(),
        "_agents_first_load_done": True,
        "_agents_filter_session_open": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_jump_to_node_unavailable_off_agents_tab() -> None:
    assert _allow(_available_app()) is True
    assert _allow(_available_app(current_tab="artifacts")) is False
    assert _allow(_available_app(current_tab="services")) is False


def test_jump_to_node_unavailable_while_editor_owns_keys() -> None:
    assert _allow(_available_app(_prompt_input_active=lambda: True)) is False


def test_jump_to_node_unavailable_before_first_load_or_during_filter_session() -> None:
    assert _allow(_available_app(_agents_first_load_done=False)) is False
    assert _allow(_available_app(_agents_filter_session_open=True)) is False


async def test_quotation_mark_opens_modal_and_hint_jumps_to_hidden_member(
    monkeypatch: Any,
) -> None:
    member_a = _clan_member("finder.a", "finder-a")
    member_b = _clan_member("finder.b", "finder-b")
    patch_startup_loaders(monkeypatch, agents=[member_a, member_b])

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        app = page.app

        # Collapse the clan fold so the members are hidden behind ``▸``.
        container = next(
            agent for agent in app._agents_with_children if agent.is_clan_container
        )
        clan_key = agent_fold_key(container)
        assert clan_key is not None
        # The clan fold starts collapsed; collapse again is a no-op.
        app._fold_manager.collapse(clan_key)
        app._refilter_agents()
        await page.pause()
        assert member_b.identity not in {agent.identity for agent in app._agents}

        origin = app._get_selected_agent()
        assert origin is not None

        # 1. ``"`` opens the modal.
        await page.press('"')
        await page.expect_modal("NodeFinderModal")

        # 2. A hint jumps to the collapsed clan member, revealed + selected.
        modal = app.screen
        hint_to_identity = dict(modal._view.hint_to_identity)
        hint = next(
            key
            for key, identity in hint_to_identity.items()
            if identity == member_b.identity
        )
        await page.press(hint)
        await page.expect_no_modal()
        await page.wait_for(
            lambda _screen: (
                app._get_selected_agent() is not None
                and app._get_selected_agent().identity == member_b.identity
            )
        )
        assert member_b.identity in {agent.identity for agent in app._agents}

        # 3. ``"`` then ``"`` jumps back to the origin row.
        await page.press('"')
        await page.expect_modal("NodeFinderModal")
        await page.press('"')
        await page.expect_no_modal()
        await page.wait_for(
            lambda _screen: (
                app._get_selected_agent() is not None
                and app._get_selected_agent().identity == origin.identity
            )
        )

        # 4. An invalid key neither dismisses nor arms leader/custom modes.
        await page.press('"')
        await page.expect_modal("NodeFinderModal")
        modal = app.screen
        live_hints = set(modal._view.hint_to_identity)
        invalid = next(key for key in ("q", "z", "x", "v") if key not in live_hints)
        await page.press(invalid)
        await page.pause()
        assert app.screen is modal
        assert app._leader_mode_active is False
        assert app._custom_mode_active is None
        await page.press("escape")
        await page.expect_no_modal()
