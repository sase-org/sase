"""Back/forward history tests for folded-banner jump hints."""

import pytest

from sase.ace.tui.actions.agents._panel_fold_intent import set_panel_fold_intent
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from tests.ace.tui._jump_hints_for_folded_banners_helpers import _agent, _StubApp


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
        _agent(project="alpha", cl="a1", name="a2", tribe="ws"),
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
    """Ctrl+Shift+O walks forward and keeps agent/banner panel focus intact."""
    agents = [
        _agent(project="alpha", cl="a1", name="a1"),
        _agent(project="alpha", cl="a1", name="a2", tribe="ws"),
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
        _agent(project="alpha", cl="a1", name="alpha", tribe="alpha"),
        _agent(project="beta", cl="b1", name="beta", tribe="beta"),
        _agent(project="gamma", cl="g1", name="gamma-one", tribe="gamma"),
        _agent(project="gamma", cl="g2", name="gamma-two", tribe="gamma"),
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
        _agent(project="chop", cl="c1", name="hidden", tribe="chop"),
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
        _agent(project="chop", cl="c1", name="hidden", tribe="chop"),
    ]
    app = _StubApp(agents, collapsed_panels={"chop"})
    app._entry_jump_agents_anchor_stack = [("panel", "chop")]
    set_panel_fold_intent(app, "chop", collapsed=False)

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
        _agent(project="alpha", cl="a1", name="a2", tribe="ws"),
    ]
    app = _StubApp(agents)
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [("agent", 1, "missing")]

    restored = app._restore_agents_jump_anchor()

    assert restored is False
    assert app._panel_group.focused_idx == 0
    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
