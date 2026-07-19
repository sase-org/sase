"""Dispatch and navigation-guard tests for folded-banner jump hints."""

from unittest.mock import Mock

import pytest

from tests.ace.tui._jump_hints_for_folded_banners_helpers import _agent, _StubApp


@pytest.fixture
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


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
        _agent(project="alpha", cl="a1", name="a2", tribe="ws"),
    ]
    # Two panels: no tribe (idx 0) and @ws (idx 1).
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
        _agent(project="alpha", cl="a1", name="a2", tribe="ws"),
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
            tribe="chop",
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
        _agent(project="chop", cl="c1", name="hidden", tribe="chop"),
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
