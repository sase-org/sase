"""Keymap plumbing and tab availability for Services J/K panel jumps."""

from __future__ import annotations

from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Label

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.keymaps import build_app_bindings, load_keymap_registry


def test_default_keymap_binds_j_k_to_both_panel_pairs() -> None:
    registry = load_keymap_registry({})

    assert registry.app.focus_next_agent_panel == "J"
    assert registry.app.focus_prev_agent_panel == "K"
    assert registry.app.focus_next_service_panel == "J"
    assert registry.app.focus_prev_service_panel == "K"

    bindings = build_app_bindings(registry.app)
    j_actions = {b.action for b in bindings if b.key == "J"}
    k_actions = {b.action for b in bindings if b.key == "K"}
    assert j_actions == {"focus_next_agent_panel", "focus_next_service_panel"}
    assert k_actions == {"focus_prev_agent_panel", "focus_prev_service_panel"}


def test_user_rebinding_of_one_j_owner_is_not_reverted() -> None:
    registry = load_keymap_registry(
        {"keymaps": {"app": {"focus_next_agent_panel": "J"}}}
    )
    assert registry.app.focus_next_agent_panel == "J"
    assert registry.app.focus_next_service_panel == "J"

    rebound = load_keymap_registry(
        {"keymaps": {"app": {"focus_next_service_panel": "B"}}}
    )
    assert rebound.app.focus_next_service_panel == "B"
    assert rebound.app.focus_next_agent_panel == "J"


def _availability(tab: str, action: str) -> bool | None:
    app = SimpleNamespace(current_tab=tab)
    return check_app_action(app, action, (), lambda _a, _p: True)


def test_agent_panel_jumps_available_only_on_agents_tab() -> None:
    assert _availability("agents", "focus_next_agent_panel") is True
    assert _availability("agents", "focus_prev_agent_panel") is True
    assert _availability("services", "focus_next_agent_panel") is False
    assert _availability("services", "focus_prev_agent_panel") is False
    assert _availability("artifacts", "focus_next_agent_panel") is False


def test_service_panel_jumps_available_only_on_services_tab() -> None:
    assert _availability("services", "focus_next_service_panel") is True
    assert _availability("services", "focus_prev_service_panel") is True
    assert _availability("agents", "focus_next_service_panel") is False
    assert _availability("agents", "focus_prev_service_panel") is False
    assert _availability("artifacts", "focus_next_service_panel") is False


class _PanelJumpPilotApp(App[None]):
    """Minimal app dispatching the real J/K bindings with tab gating."""

    ENABLE_COMMAND_PALETTE = False
    BINDINGS = build_app_bindings(load_keymap_registry({}).app)

    def __init__(self) -> None:
        super().__init__()
        self.current_tab = "services"
        self.ran: list[str] = []

    def compose(self) -> ComposeResult:
        yield Label("panel jumps")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return check_app_action(self, action, parameters, super().check_action)

    def action_focus_next_agent_panel(self) -> None:
        self.ran.append("agent_next")

    def action_focus_prev_agent_panel(self) -> None:
        self.ran.append("agent_prev")

    def action_focus_next_service_panel(self) -> None:
        self.ran.append("service_next")

    def action_focus_prev_service_panel(self) -> None:
        self.ran.append("service_prev")


async def test_pilot_j_k_run_services_actions_on_services_tab() -> None:
    app = _PanelJumpPilotApp()
    async with app.run_test() as pilot:
        await pilot.press("J", "K")
        await pilot.pause()
        assert app.ran == ["service_next", "service_prev"]


async def test_pilot_j_k_run_agent_actions_on_agents_tab() -> None:
    app = _PanelJumpPilotApp()
    app.current_tab = "agents"
    async with app.run_test() as pilot:
        await pilot.press("J", "K")
        await pilot.pause()
        assert app.ran == ["agent_next", "agent_prev"]
