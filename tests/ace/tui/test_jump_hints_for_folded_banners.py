"""Jump hints cover collapsed group banners and panel titles on the Agents tab.

Pressing ``'`` should paint a ``[x]`` chip next to every collapsed banner
row alongside the visible-agent chips and every split-panel title, so a single
keystroke can land on an agent, focus a folded group banner, or focus a panel
in either its collapsed or expanded state. Expanded banners stay hint-less.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest

from sase.ace.tui.actions.agents._unread import AgentUnreadMixin
from sase.ace.tui.actions.navigation._advanced import AdvancedNavigationMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_panels import AgentPanelGroup


class _StubApp(AgentUnreadMixin, AdvancedNavigationMixin):
    """Minimal harness for the agents-tab jump-mode helpers."""

    def __init__(
        self,
        agents: list[Agent],
        *,
        collapsed: list[tuple[str, ...]] | None = None,
        collapsed_by_panel: dict[str | None, list[tuple[str, ...]]] | None = None,
        collapsed_panels: set[str | None] | None = None,
        patch_result: bool = True,
    ) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.current_attempt_number: int | None = 7
        self._agents = agents
        self._group_fold_registry = AgentGroupFoldRegistry()
        for key in collapsed or []:
            self._group_fold_registry.collapse(key)
        for panel_key, keys in (collapsed_by_panel or {}).items():
            self._group_fold_registry.for_panel(panel_key).collapse_keys(keys)
        self._collapsed_panel_keys = set(collapsed_panels or ())
        self._panel_group = AgentPanelGroup.from_agents(
            agents,
            collapsed_panel_keys=self._collapsed_panel_keys,
        )
        self._current_group_key: tuple[str, ...] | None = None
        self._entry_jump_mode_active = False
        self._entry_jump_hint_to_index: dict[str, int] = {}
        self._entry_jump_index_to_hint: dict[int, str] = {}
        self._entry_jump_hint_to_banner: dict[str, Any] = {}
        self._entry_jump_banner_to_hint: dict[Any, str] = {}
        self._entry_jump_hint_to_panel: dict[str, Any] = {}
        self._entry_jump_panel_to_hint: dict[Any, str] = {}
        self._entry_jump_index_stack: dict[str, list[int]] = {}
        self._entry_jump_forward_index_stack: dict[str, list[Any]] = {}
        self._entry_jump_agents_anchor_stack: list[Any] = []
        self._entry_jump_agents_forward_anchor_stack: list[Any] = []
        self._unread_completed_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._manual_unread_agent_ids: set[tuple[AgentType, str, str | None]] = set()
        self._agent_info_metrics_cache: tuple[Any, ...] | None = None
        self._patch_result = patch_result
        self.patch_calls: list[Agent] = []
        self.refresh_calls: list[dict[str, Any]] = []
        self.notification_count_refresh_calls = 0
        self.artifact_file_viewer_guard_active = False
        self.jump_footer_updates = 0
        self.notify = MagicMock()

    def _guard_agent_navigation_for_artifact_file_viewer(self) -> bool:
        if not self.artifact_file_viewer_guard_active:
            return False
        self.notify(
            "Close the artifact viewer before switching agents",
            severity="warning",
        )
        return True

    def _panel_keys_per_agent(self) -> list:
        from sase.ace.tui.models.agent_panels import panel_key_per_agent

        return panel_key_per_agent(self._agents)

    def _snap_current_idx_to_focused_panel(
        self, keys_per_agent: list[str | None], focused_key: str | None
    ) -> None:
        for index, panel_key in enumerate(keys_per_agent):
            if panel_key == focused_key:
                self.current_idx = index
                return
        self.current_idx = 0

    # The mixin would normally drive a full refresh; tests don't render, but
    # unread assertions need to know whether refresh fallback was requested.
    def _refresh_agents_display(self, **kwargs: Any) -> None:
        self.refresh_calls.append(kwargs)

    def _refresh_current_tab(self) -> None:
        return

    def _update_jump_footer(self) -> None:
        self.jump_footer_updates += 1

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        self.patch_calls.append(agent)
        return self._patch_result

    def _refresh_notification_count(self) -> None:
        self.notification_count_refresh_calls += 1


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def _agent(
    *,
    project: str,
    cl: str,
    name: str,
    tag: str | None = None,
    status: str = "RUNNING",
    raw_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl,
        project_file=f"/r/{project}/proj.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tag=tag,
        raw_suffix=raw_suffix,
    )


def test_jump_targets_includes_collapsed_banners() -> None:
    """Targets list should contain a banner entry before its agent rows."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
        _agent(project="beta", cl="b1", name="b2"),
    ]
    # Collapse the alpha L0 banner so its single agent disappears and the
    # banner itself becomes a target.  beta agents stay visible.
    app = _StubApp(agents, collapsed=[("alpha",)])

    targets = app._jump_candidate_targets()

    assert ("banner", 0, ("alpha",)) in targets
    # The two beta agents are still visible.
    agent_targets = [t for t in targets if t[0] == "agent"]
    assert ("agent", 1) in agent_targets
    assert ("agent", 2) in agent_targets


def test_jump_targets_include_expanded_panel_but_skip_expanded_banners() -> None:
    """Expanded panel titles precede rows; expanded banners stay untargeted."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)

    targets = app._jump_candidate_targets()

    banner_targets = [t for t in targets if t[0] == "banner"]
    assert banner_targets == []
    assert targets == [("panel", None), ("agent", 0), ("agent", 1)]


def test_jump_targets_include_collapsed_panels_in_render_order() -> None:
    agents = [
        _agent(project="alpha", cl="a1", name="hidden-group"),
        _agent(project="beta", cl="b1", name="visible"),
        _agent(project="chop", cl="c1", name="hidden-one", tag="chop"),
        _agent(project="chop", cl="c2", name="hidden-two", tag="chop"),
        _agent(project="zoom", cl="z1", name="hidden-zoom", tag="zoom"),
    ]
    app = _StubApp(
        agents,
        collapsed=[("alpha",)],
        collapsed_panels={"chop", "zoom"},
    )

    assert app._panel_group.panel_keys == [None, "chop", "zoom"]
    assert app._jump_candidate_targets() == [
        ("panel", None),
        ("banner", 0, ("alpha",)),
        ("agent", 1),
        ("panel", "chop"),
        ("panel", "zoom"),
    ]


def test_all_panel_maps_use_stable_keys_including_untagged() -> None:
    agents = [
        _agent(project="home", cl="u1", name="untagged"),
        _agent(project="apple", cl="a1", name="visible", tag="apple"),
        _agent(project="chop", cl="c1", name="hidden", tag="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={None, "chop"})

    app._begin_agents_jump_mode()

    assert app._entry_jump_hint_to_panel == {
        "1": ("panel", "apple"),
        "3": ("panel", None),
        "4": ("panel", "chop"),
    }
    assert app._entry_jump_panel_to_hint == {
        ("panel", "apple"): "1",
        ("panel", None): "3",
        ("panel", "chop"): "4",
    }


def test_jump_dispatch_banner_sets_group_key() -> None:
    """Selecting a banner hint sets ``_current_group_key`` without moving the agent."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1  # cursor sits on a beta agent
    app._begin_agents_jump_mode()

    # Find the hint allocated to the alpha banner target.
    banner_target = ("banner", 0, ("alpha",))
    hint = app._entry_jump_banner_to_hint[banner_target]

    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app._current_group_key == ("alpha",)
    # The agent index must not have moved — banner selection is purely
    # about the group highlight.
    assert app.current_idx == 1


def test_jump_dispatch_banner_switches_focused_panel() -> None:
    """Banner targets in a non-focused panel change ``focused_idx``."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    # Two panels: untagged (idx 0) and @ws (idx 1).
    app = _StubApp(agents, collapsed_by_panel={"ws": [("alpha",)]})
    assert app._panel_group.panel_keys == [None, "ws"]
    assert app._panel_group.focused_idx == 0

    app._begin_agents_jump_mode()

    # Pick out the banner hint that lives in panel 1 (the @ws panel).
    target = next(t for t in app._entry_jump_hint_to_banner.values() if t[1] == 1)
    hint = app._entry_jump_banner_to_hint[target]

    app._handle_entry_jump_key(hint)

    assert app._panel_group.focused_idx == 1
    assert app._current_group_key == target[2]


def test_jump_dispatch_agent_switches_focused_panel() -> None:
    """Agent targets in a non-focused panel move panel focus with the cursor."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    app = _StubApp(agents)
    app.current_idx = 0
    assert app._panel_group.panel_keys == [None, "ws"]
    assert app._panel_group.focused_idx == 0

    app._begin_agents_jump_mode()
    hint = app._entry_jump_index_to_hint[1]

    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app.current_idx == 1
    assert app._panel_group.focused_idx == 1
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]


def test_jump_dispatch_agent_acknowledges_unread_done_and_patches_row(
    notification_dismiss: Mock,
) -> None:
    """Jumping to an unread terminal agent clears the marker through row patching."""
    notification_dismiss.return_value = 1
    agents = [
        _agent(project="alpha", cl="a1", name="a1", raw_suffix="a1"),
        _agent(
            project="beta",
            cl="b1",
            name="done",
            status="DONE",
            raw_suffix="done",
        ),
    ]
    app = _StubApp(agents)
    target = agents[1]
    app._unread_completed_agent_ids.add(target.identity)

    app._begin_agents_jump_mode()
    handled = app._handle_entry_jump_key(app._entry_jump_index_to_hint[1])

    assert handled is True
    assert app.current_idx == 1
    assert target.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [target]
    notification_dismiss.assert_called_once_with(
        [{"cl_name": target.cl_name, "raw_suffix": target.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_jump_dispatch_manual_unread_target_stays_guarded(
    notification_dismiss: Mock,
) -> None:
    """A manually unread target is selected but not auto-acknowledged."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1", raw_suffix="a1"),
        _agent(
            project="beta",
            cl="b1",
            name="manual",
            status="DONE",
            raw_suffix="manual",
        ),
    ]
    app = _StubApp(agents)
    target = agents[1]
    app._unread_completed_agent_ids.add(target.identity)
    app._manual_unread_agent_ids.add(target.identity)

    app._begin_agents_jump_mode()
    handled = app._handle_entry_jump_key(app._entry_jump_index_to_hint[1])

    assert handled is True
    assert app.current_idx == 1
    assert target.identity in app._unread_completed_agent_ids
    assert target.identity in app._manual_unread_agent_ids
    assert app.patch_calls == []
    notification_dismiss.assert_not_called()


def test_jump_dispatch_arms_manual_unread_departure_before_return(
    notification_dismiss: Mock,
) -> None:
    """Leaving a manually unread row arms it so a later jump back can read it."""
    notification_dismiss.return_value = 1
    agents = [
        _agent(
            project="alpha",
            cl="a1",
            name="manual",
            status="DONE",
            raw_suffix="manual",
        ),
        _agent(project="beta", cl="b1", name="b1", raw_suffix="b1"),
    ]
    app = _StubApp(agents)
    manual_agent = agents[0]
    app._unread_completed_agent_ids.add(manual_agent.identity)
    app._manual_unread_agent_ids.add(manual_agent.identity)

    app._begin_agents_jump_mode()
    app._handle_entry_jump_key(app._entry_jump_index_to_hint[1])

    assert manual_agent.identity in app._unread_completed_agent_ids
    assert manual_agent.identity not in app._manual_unread_agent_ids
    assert app.patch_calls == []

    app._begin_agents_jump_mode()
    app._handle_entry_jump_key(app._entry_jump_index_to_hint[0])

    assert app.current_idx == 0
    assert manual_agent.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [manual_agent]
    notification_dismiss.assert_called_once_with(
        [{"cl_name": manual_agent.cl_name, "raw_suffix": manual_agent.raw_suffix}]
    )


def test_jump_dispatch_banner_arms_manual_departure_without_acknowledging_agent(
    notification_dismiss: Mock,
) -> None:
    """Banner targets focus the banner and leave all agent unread markers intact."""
    agents = [
        _agent(
            project="alpha",
            cl="a1",
            name="hidden",
            status="DONE",
            raw_suffix="hidden",
        ),
        _agent(
            project="beta",
            cl="b1",
            name="manual",
            status="DONE",
            raw_suffix="manual",
        ),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    hidden_agent = agents[0]
    manual_agent = agents[1]
    app.current_idx = 1
    app._unread_completed_agent_ids.update(
        {hidden_agent.identity, manual_agent.identity}
    )
    app._manual_unread_agent_ids.add(manual_agent.identity)

    app._begin_agents_jump_mode()
    handled = app._handle_entry_jump_key(
        app._entry_jump_banner_to_hint[("banner", 0, ("alpha",))]
    )

    assert handled is True
    assert app._current_group_key == ("alpha",)
    assert app.current_idx == 1
    assert hidden_agent.identity in app._unread_completed_agent_ids
    assert manual_agent.identity in app._unread_completed_agent_ids
    assert manual_agent.identity not in app._manual_unread_agent_ids
    assert app.patch_calls == []
    notification_dismiss.assert_not_called()


def test_jump_dispatch_panel_reanchors_without_acknowledging_hidden_agent(
    notification_dismiss: Mock,
) -> None:
    agents = [
        _agent(
            project="home",
            cl="source",
            name="manual",
            status="DONE",
            raw_suffix="manual",
        ),
        _agent(
            project="chop",
            cl="hidden",
            name="hidden",
            tag="chop",
            status="DONE",
            raw_suffix="hidden",
        ),
    ]
    app = _StubApp(agents, collapsed_panels={"chop"})
    source, hidden = agents
    app._unread_completed_agent_ids.update({source.identity, hidden.identity})
    app._manual_unread_agent_ids.add(source.identity)

    app._begin_agents_jump_mode()
    hint = app._entry_jump_panel_to_hint[("panel", "chop")]
    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app._panel_group.focused_key == "chop"
    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert source.identity in app._unread_completed_agent_ids
    assert source.identity not in app._manual_unread_agent_ids
    assert hidden.identity in app._unread_completed_agent_ids
    assert app.patch_calls == []
    notification_dismiss.assert_not_called()


def test_jump_mode_entry_guard_warns_without_entering() -> None:
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)
    app.artifact_file_viewer_guard_active = True

    app._begin_agents_jump_mode()

    assert app._entry_jump_mode_active is False
    assert app._entry_jump_hint_to_index == {}
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )


def test_jump_selection_guard_keeps_current_agent() -> None:
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents)
    app.current_idx = 0
    app._begin_agents_jump_mode()
    hint = app._entry_jump_index_to_hint[1]
    app.artifact_file_viewer_guard_active = True

    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_mode_active is False
    app.notify.assert_called_once_with(
        "Close the artifact viewer before switching agents",
        severity="warning",
    )


def test_panel_jump_selection_guard_keeps_focus_and_backing_agent() -> None:
    agents = [
        _agent(project="home", cl="u1", name="source"),
        _agent(project="chop", cl="c1", name="hidden", tag="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={"chop"})
    app._begin_agents_jump_mode()
    hint = app._entry_jump_panel_to_hint[("panel", "chop")]
    app.artifact_file_viewer_guard_active = True

    handled = app._handle_entry_jump_key(hint)

    assert handled is True
    assert app._panel_group.focused_key is None
    assert app.current_idx == 0
    assert app._entry_jump_mode_active is False
    assert app._entry_jump_hint_to_panel == {}
    assert app._entry_jump_panel_to_hint == {}


def test_back_jump_restores_agent_anchor() -> None:
    """``'`` after an agent→banner jump returns to the original agent."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1  # cursor starts on the beta agent

    # First press: pick the alpha banner.
    app._begin_agents_jump_mode()
    banner_hint = next(iter(app._entry_jump_hint_to_banner))
    app._handle_entry_jump_key(banner_hint)
    assert app._current_group_key == ("alpha",)

    # Second press: ``'`` again should restore the prior agent cursor.
    app._begin_agents_jump_mode()
    app._handle_entry_jump_key("apostrophe")

    assert app._current_group_key is None
    assert app.current_idx == 1


def test_apostrophe_without_anchor_dispatches_first_expanded_panel_hint() -> None:
    """No-history ``'`` follows hint ``1`` through expanded-panel dispatch."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1

    app._begin_agents_jump_mode()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app._current_group_key is None
    assert app._expanded_panel_focus is True
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]
    assert app._entry_jump_mode_active is False

    app._begin_agents_jump_mode()
    assert app._handle_entry_jump_key("apostrophe") is True
    assert app._expanded_panel_focus is False
    assert app.current_idx == 1


def test_fast_jump_without_anchor_dispatches_first_expanded_panel_hint() -> None:
    """Fast jump follows no-history ``''`` without painting hint UI."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1

    app.action_jump_to_entry_fast()

    assert app._current_group_key is None
    assert app._expanded_panel_focus is True
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_restores_agent_banner_anchor_with_panel_focus() -> None:
    """Fast jump restores saved banner anchors with their owning panel."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    app = _StubApp(agents, collapsed_by_panel={"ws": [("alpha",)]})
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [("banner", "ws", ("alpha",))]

    app.action_jump_to_entry_fast()

    assert app._panel_group.focused_idx == 1
    assert app._current_group_key == ("alpha",)
    assert app._entry_jump_agents_anchor_stack == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_agent_forward_jump_restores_panel_and_banner_anchors() -> None:
    """Ctrl+K walks forward and keeps agent/banner panel focus intact."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    app = _StubApp(agents, collapsed_by_panel={"ws": [("alpha",)]})
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [("banner", "ws", ("alpha",))]

    app.action_jump_to_entry_fast()

    assert app._panel_group.focused_idx == 1
    assert app._current_group_key == ("alpha",)
    assert app._entry_jump_agents_forward_anchor_stack == [("agent", 0, None)]

    app.action_jump_to_entry_forward()

    assert app._panel_group.focused_idx == 0
    assert app._current_group_key is None
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == [("banner", "ws", ("alpha",))]
    assert app._entry_jump_agents_forward_anchor_stack == []


def test_banner_history_survives_whole_panel_repartition() -> None:
    agents = [
        _agent(project="alpha", cl="a1", name="alpha", tag="alpha"),
        _agent(project="beta", cl="b1", name="beta", tag="beta"),
        _agent(project="gamma", cl="g1", name="gamma-one", tag="gamma"),
        _agent(project="gamma", cl="g2", name="gamma-two", tag="gamma"),
    ]
    app = _StubApp(
        agents,
        collapsed_by_panel={"gamma": [("gamma",)]},
        collapsed_panels={"alpha"},
    )
    assert app._panel_group.panel_keys == ["beta", "gamma", "alpha"]
    app._panel_group.focused_idx = 1
    app._current_group_key = ("gamma",)
    app.current_idx = 2
    app._save_agents_jump_anchor()
    assert app._entry_jump_agents_anchor_stack == [("banner", "gamma", ("gamma",))]

    app._collapsed_panel_keys.clear()
    app._panel_group = AgentPanelGroup.from_agents(agents, focused_key="beta")
    app._current_group_key = None
    app.current_idx = 1
    assert app._panel_group.panel_keys == ["alpha", "beta", "gamma"]

    assert app._restore_agents_jump_anchor()
    assert app._panel_group.focused_key == "gamma"
    assert app._panel_group.focused_idx == 2
    assert app._current_group_key == ("gamma",)

    app.action_jump_to_entry_forward()
    assert app._panel_group.focused_key == "beta"
    assert app.current_idx == 1


def test_panel_anchor_round_trips_through_back_and_forward_history() -> None:
    agents = [
        _agent(project="home", cl="u1", name="source"),
        _agent(project="chop", cl="c1", name="hidden", tag="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={"chop"})

    app._begin_agents_jump_mode()
    app._handle_entry_jump_key(app._entry_jump_panel_to_hint[("panel", "chop")])
    assert app._current_agents_jump_anchor() == ("panel", "chop")

    app._begin_agents_jump_mode()
    app._handle_entry_jump_key("apostrophe")
    assert app._panel_group.focused_key is None
    assert app.current_idx == 0
    assert app._entry_jump_agents_forward_anchor_stack == [("panel", "chop")]

    app.action_jump_to_entry_forward()
    assert app._panel_group.focused_key == "chop"
    assert app.current_idx == 1
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app._entry_jump_agents_forward_anchor_stack == []


@pytest.mark.parametrize("fast", [False, True])
def test_no_history_apostrophe_can_select_first_collapsed_panel(fast: bool) -> None:
    agents = [_agent(project="home", cl="u1", name="hidden")]
    app = _StubApp(agents, collapsed_panels={None})

    if fast:
        app.action_jump_to_entry_fast()
    else:
        app._begin_agents_jump_mode()
        app._handle_entry_jump_key("apostrophe")

    assert app._panel_group.focused_key is None
    assert app.current_idx == 0
    assert app._current_agents_jump_anchor() == ("panel", None)
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == (0 if fast else 1)


def test_panel_anchor_restores_expanded_focus_but_discards_removed_panel() -> None:
    agents = [
        _agent(project="home", cl="u1", name="source"),
        _agent(project="chop", cl="c1", name="hidden", tag="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={"chop"})
    app._entry_jump_agents_anchor_stack = [("panel", "chop")]
    app._collapsed_panel_keys.clear()

    assert app._restore_agents_jump_anchor() is True
    assert app._entry_jump_agents_anchor_stack == []
    assert app._panel_group.focused_key == "chop"
    assert app._expanded_panel_focus is True

    app._collapsed_panel_keys.add("chop")
    app._entry_jump_agents_anchor_stack = [("panel", "chop")]
    app._panel_group = AgentPanelGroup.from_agents([agents[0]])

    assert app._restore_agents_jump_anchor() is False
    assert app._entry_jump_agents_anchor_stack == []
    assert app._panel_group.focused_key is None


def test_fast_jump_pops_agent_anchor_stack_lifo() -> None:
    """Repeated fast jumps walk backward through agent and banner anchors."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
        _agent(project="beta", cl="b2", name="b2"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [
        ("agent", 2, None),
        ("banner", None, ("alpha",)),
        ("agent", 1, None),
    ]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 1
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [
        ("agent", 2, None),
        ("banner", None, ("alpha",)),
    ]

    app.action_jump_to_entry_fast()
    assert app._current_group_key == ("alpha",)
    assert app._entry_jump_agents_anchor_stack == [("agent", 2, None)]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 2
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == []


def test_stale_agent_back_anchor_falls_through_to_first_hint() -> None:
    """Out-of-range agent anchors are ignored so ``'`` can dispatch hint ``1``."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1
    app._entry_jump_agents_anchor_stack = [("agent", 99, None)]

    app._begin_agents_jump_mode()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app._current_group_key is None
    assert app._expanded_panel_focus is True
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]


def test_stale_agent_banner_anchor_falls_through_to_first_hint() -> None:
    """Banner anchors that no longer exist are popped before hint fallback."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="beta", cl="b1", name="b1"),
    ]
    app = _StubApp(agents, collapsed=[("alpha",)])
    app.current_idx = 1
    app._entry_jump_agents_anchor_stack = [("banner", None, ("missing",))]

    app.action_jump_to_entry_fast()

    assert app._current_group_key is None
    assert app._expanded_panel_focus is True
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]


def test_invalid_panel_back_anchor_does_not_change_focused_panel() -> None:
    """Missing panel keys are stale and must not be assigned during restore."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tag="ws"),
    ]
    app = _StubApp(agents)
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [("agent", 1, "missing")]

    restored = app._restore_agents_jump_anchor()

    assert restored is False
    assert app._panel_group.focused_idx == 0
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
