"""Wire-phase coverage for context-aware Enter (sase-16j.3)."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.binding import Binding

from sase.ace.tui.actions.agents._agent_enter_action import AgentEnterActionMixin
from sase.ace.tui.actions.agents._agent_enter_targets import (
    enter_action_label_for_targets,
    resolve_agent_enter_targets,
)
from sase.ace.tui.actions.agents._notification_provider import (
    AgentNotificationProviderMixin,
)
from sase.ace.tui.commands import build_command_catalog, is_command_available
from sase.ace.tui.commands.types import CommandContext
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.modals.help_modal.agents_bindings import agents_bindings
from sase.ace.tui.widgets import KeybindingFooter
from sase.notifications import Notification
from tests.ace.tui._agent_unread_helpers import make_agent


def _notification(
    notification_id: str,
    action: str | None,
    *,
    action_data: dict[str, str] | None = None,
) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-09-18T12:00:00+00:00",
        sender="test",
        action=action,
        action_data=dict(action_data or {}),
    )


def _matching_action_data(agent: Agent) -> dict[str, str]:
    assert agent.raw_suffix is not None
    data: dict[str, str] = {
        "agent_cl_name": agent.cl_name,
        "agent_timestamp": agent.raw_suffix,
    }
    if agent.agent_name:
        data["agent_name"] = agent.agent_name
    return data


def _gate_row(
    suffix: str,
    *,
    gate_id: str = "gate-abc123",
    notification_id: str | None = None,
) -> Agent:
    return replace(
        make_agent(
            name=f"gate-{suffix}",
            status="GATE",
            raw_suffix=f"20260918{suffix}",
        ),
        agent_family_role="gate",
        gate_id=gate_id,
        gate_kind="sudo",
        gate_state="pending",
        gate_start_status="SUDO",
        gate_notification_id=notification_id,
    )


def _patch_name_for(agent: Agent) -> str | None:
    name = agent.cl_name
    if not name or name in {"unknown", "~"}:
        return None
    return name


# ---------------------------------------------------------------------------
# Keymaps and registry
# ---------------------------------------------------------------------------


def test_act_on_agent_bound_to_enter_and_patch_unbound() -> None:
    reg = load_keymap_registry({})
    assert reg.app.act_on_agent == "enter"
    assert reg.app.jump_to_agent_patch == "unbound"
    assert "jump_to_notification" not in reg.leader_mode.keys


def test_stale_jump_to_notification_override_warns_and_drops(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "leader_mode": {
                            "keys": {
                                "jump_to_notification": "n",
                                "collapse_fold_by_hint": "C",
                            }
                        }
                    }
                }
            }
        )
    assert "jump_to_notification" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["collapse_fold_by_hint"] == "C"
    assert "stale leader_mode.keys.jump_to_notification" in caplog.text
    assert "ace.keymaps.app.act_on_agent" in caplog.text


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


def test_act_on_agent_catalog_entry_and_leader_removed() -> None:
    from sase.ace.tui.commands import get_command_by_id

    catalog = build_command_catalog(load_keymap_registry({}))
    spec = get_command_by_id(catalog, "app.act_on_agent")
    assert spec is not None
    assert spec.label == "Act on agent (gate or Patch)"
    assert "review gate" in spec.aliases
    assert "go to patch" in spec.aliases
    assert get_command_by_id(catalog, "leader.jump_to_notification") is None


def test_act_on_agent_needs_enter_target() -> None:
    from tests._command_availability_helpers import catalog_by_id, make_agent

    catalog = catalog_by_id()
    spec = catalog["app.act_on_agent"]
    agent = make_agent()
    assert not is_command_available(
        spec, CommandContext(tab="agents", agent=agent, agent_enter_available=False)
    )
    assert is_command_available(
        spec, CommandContext(tab="agents", agent=agent, agent_enter_available=True)
    )
    assert not is_command_available(spec, CommandContext(tab="agents", agent=None))


def test_act_on_agent_stays_available_on_remote_rows() -> None:
    from sase.ace.tui.models.agent import AgentType

    from tests._command_availability_helpers import catalog_by_id
    from sase.ace.tui.commands._availability_agents import (
        _REMOTE_AGENT_LOCAL_COMMANDS,
    )

    catalog = catalog_by_id()
    assert "app.act_on_agent" not in _REMOTE_AGENT_LOCAL_COMMANDS
    remote = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fleet-ui",
        project_file="/fleet/apollo/project.yml",
        status="RUNNING",
        start_time=None,
        fleet_origin_alias="apollo",
    )
    ctx = CommandContext(
        tab="agents",
        agent=remote,
        selected_agent_remote=True,
        agent_enter_available=True,
    )
    assert is_command_available(catalog["app.act_on_agent"], ctx)


# ---------------------------------------------------------------------------
# Footer labels
# ---------------------------------------------------------------------------


def test_enter_action_label_for_targets() -> None:
    assert enter_action_label_for_targets(()) is None
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    resolution = resolve_agent_enter_targets(
        agent,
        gate_notifications=SimpleNamespace(
            by_id={}, by_bundle_path={}, by_raw_suffix={}, gate_notifications=()
        ),
        patch_name_for=_patch_name_for,
        patch_lookup=lambda _name: None,
    )
    assert len(resolution.targets) == 1
    assert enter_action_label_for_targets(resolution.targets) == "go to patch"


def test_footer_enter_hint_primary_and_secondary() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    agent = make_agent()
    # One target: Enter hint, no direct Patch hint (unbound by default).
    bindings = footer._compute_agent_bindings(
        agent, can_jump_to_patch=True, enter_action_label="review sudo request"
    )
    assert (footer._kd("act_on_agent"), "review sudo request") in bindings
    assert footer._kd("act_on_agent") == "<enter>"
    assert not any(label == "go to PR" for _, label in bindings)
    # Two targets: choose action.
    bindings = footer._compute_agent_bindings(
        agent, can_jump_to_patch=True, enter_action_label="choose action"
    )
    assert (footer._kd("act_on_agent"), "choose action") in bindings
    # Zero targets: no Enter hint.
    bindings = footer._compute_agent_bindings(
        agent, can_jump_to_patch=False, enter_action_label=None
    )
    assert not any(key == footer._kd("act_on_agent") for key, _ in bindings)
    # Rebound direct Patch key shows the secondary hint.
    reg = load_keymap_registry({"keymaps": {"app": {"jump_to_agent_patch": "f9"}}})
    footer.set_keymap_registry(reg)
    assert reg.app.jump_to_agent_patch == "f9"
    bindings = footer._compute_agent_bindings(
        agent, can_jump_to_patch=True, enter_action_label="go to patch"
    )
    assert (footer._kd("jump_to_agent_patch"), "go to PR") in bindings


def test_footer_enter_sorts_first() -> None:
    footer = KeybindingFooter()
    footer.set_keymap_registry(load_keymap_registry({}))
    agent = make_agent()
    bindings = footer._compute_agent_bindings(
        agent, enter_action_label="review sudo request"
    )
    ordered = footer._sorted_bindings(bindings)
    assert ordered[0] == (footer._kd("act_on_agent"), "review sudo request")


# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------


def test_agents_help_has_enter_row_and_no_leader_n() -> None:
    reg = load_keymap_registry({})
    pairs = {(key, label) for _s, rows in agents_bindings(reg) for key, label in rows}
    assert ("Enter", "Review gate / go to Patch") in pairs
    assert not any(label == "Jump to any agent notification" for _, label in pairs)


# ---------------------------------------------------------------------------
# Textual pilots
# ---------------------------------------------------------------------------


class _WireApp(
    App[None],
    AgentEnterActionMixin,
    AgentNotificationProviderMixin,
):
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("enter", "act_on_agent", show=False)]

    def __init__(
        self,
        agent: Agent,
        notifications: list[Notification] | None = None,
    ) -> None:
        super().__init__()
        self._agents = [agent]
        self._agents_with_children = [agent]
        self.current_idx = 0
        self.current_tab = "agents"
        self._current_group_key = None
        self._notification_snapshot_cache: Any = SimpleNamespace(
            notifications=list(notifications or [])
        )
        self.patches: list[Any] = []
        self.notifies: list[tuple[str, str]] = []
        self.patched: list[tuple[str, str]] = []
        self.refreshes = 0

    def compose(self) -> ComposeResult:
        from sase.ace.tui.widgets.agent_list import AgentList

        yield AgentList(id="agent-list")

    def on_mount(self) -> None:
        from sase.ace.tui.widgets.agent_list import AgentList

        agent_list = self.query_one(AgentList)
        agent_list.update_list(list(self._agents), current_idx=0)
        agent_list.focus()

    def notify(self, message: str, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        severity = kwargs.get("severity", "information")
        if args and isinstance(args[0], str):
            # Textual passes severity positionally in some paths; keep it simple.
            severity = args[0]
        self.notifies.append((message, str(severity)))

    def _get_selected_agent(self) -> Agent | None:
        return self._agents[self.current_idx] if self._agents else None

    def _resolve_agent_cl_name(self, agent: Agent) -> str | None:
        return _patch_name_for(agent)

    def _agent_by_identity(self, identity: tuple[object, ...]) -> Agent | None:
        for agent in self._agents:
            if agent.identity == identity:
                return agent
        return None

    def _open_question_modal_from_marker(self, agent: Agent) -> bool:
        del agent
        return False

    def _answer_workflow_hitl(self, agent: Agent) -> None:
        del agent
        self.notifies.append(("hitl", "information"))

    def _answer_remote_attention_for(self, agent: Any) -> None:
        from sase.ace.tui.modals.remote_attention_modal import RemoteAttentionModal

        alias = getattr(agent, "fleet_origin_alias", None) or "remote"
        attention = getattr(agent, "fleet_attention", None) or {}
        self.push_screen(RemoteAttentionModal(alias=alias, entry=dict(attention)))

    def _schedule_notification_snapshot_refresh(self) -> None:
        self.refreshes += 1

    def _read_notification_pending_actions_from_provider(self) -> object:
        return object()


async def _press_enter(app: _WireApp) -> Any:
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        return pilot


async def test_enter_patch_only_navigates_to_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    app = _WireApp(agent)
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_patch_tab",
        lambda _app, patch_name, project_file: (
            calls.append((patch_name, project_file)) or True
        ),
    )
    await _press_enter(app)
    assert calls == [("demo", agent.project_file)]


async def test_enter_sudo_gate_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _gate_row("010101", notification_id="n-sudo")
    notification = _notification(
        "n-sudo", "SudoRequest", action_data=_matching_action_data(agent)
    )
    app = _WireApp(agent, [notification])
    # Suppress the Patch target so the gate runs directly.
    app._resolve_agent_cl_name = lambda _a: None  # type: ignore[method-assign]
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda _app, note: dispatched.append(note.id) or True,
    )
    await _press_enter(app)
    assert dispatched == ["n-sudo"]


async def test_enter_gate_plus_patch_chooser_p_selects_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    notification = _notification(
        "n-plan", "PlanApproval", action_data=_matching_action_data(agent)
    )
    app = _WireApp(agent, [notification])
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_navigation.navigate_to_patch_tab",
        lambda _app, patch_name, project_file: (
            calls.append((patch_name, project_file)) or True
        ),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
    assert calls == [("demo", agent.project_file)]


async def test_enter_gate_plus_patch_chooser_g_selects_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    notification = _notification(
        "n-plan", "PlanApproval", action_data=_matching_action_data(agent)
    )
    app = _WireApp(agent, [notification])
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda _app, note: dispatched.append(note.id) or True,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("g")
        await pilot.pause()
    assert dispatched == ["n-plan"]


async def test_enter_enter_opens_primary_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    notification = _notification(
        "n-plan", "PlanApproval", action_data=_matching_action_data(agent)
    )
    app = _WireApp(agent, [notification])
    dispatched: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._notification_dispatch.open_notification_action",
        lambda _app, note: dispatched.append(note.id) or True,
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert dispatched == ["n-plan"]


async def test_enter_chooser_esc_cancels() -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    notification = _notification(
        "n-plan", "PlanApproval", action_data=_matching_action_data(agent)
    )
    app = _WireApp(agent, [notification])
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.notifies == []


async def test_enter_clan_toasts() -> None:
    agent = make_agent(name="demo", raw_suffix="20260918010101")
    agent.is_clan_container = True  # type: ignore[attr-defined]
    app = _WireApp(agent)
    await _press_enter(app)
    assert app.notifies == [("Select an agent inside this clan", "warning")]


async def test_enter_remote_attention_opens_modal() -> None:
    agent = replace(
        make_agent(name="remote-row", raw_suffix="20260918010101"),
        fleet_origin_alias="farhost",
        fleet_attention={"state": "pending", "kind": "question", "title": "Help?"},
        fleet_capabilities={"resource": ["attention.answer_question"]},
    )
    app = _WireApp(agent)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        from sase.ace.tui.modals.remote_attention_modal import RemoteAttentionModal

        assert isinstance(app.screen, RemoteAttentionModal)
