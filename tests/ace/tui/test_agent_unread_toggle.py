"""Unread agent toggle and bulk acknowledgment tests."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp
from sase.ace.tui.actions.agents._unread_state import BulkUnreadToggleOutcome
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.notifications import Notification


@pytest.fixture(autouse=True)
def notification_dismiss(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    return dismiss


def _completion_notification(agent, *, notification_id: str) -> Notification:
    return Notification(
        id=notification_id,
        timestamp="2026-08-16T12:00:00",
        sender="user-agent",
        action="JumpToAgent",
        action_data={
            "cl_name": agent.cl_name,
            "raw_suffix": agent.raw_suffix or "",
        },
    )


def test_toggle_agent_unread_marks_selected_row_without_moving(
    notification_dismiss: Mock,
) -> None:
    agent = make_agent(status="RUNNING")
    app = UnreadJumpApp([agent])

    app._toggle_agent_unread()

    assert app.current_idx == 0
    assert app._unread_completed_agent_ids == {agent.identity}
    assert app._manual_unread_agent_ids == {agent.identity}
    assert app.patch_calls == [agent]
    assert app.refresh_calls == []
    notification_dismiss.assert_not_called()


def test_toggle_agent_unread_again_marks_selected_row_read(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 1
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == [agent]
    notification_dismiss.assert_called_once_with(
        [{"cl_name": agent.cl_name, "raw_suffix": agent.raw_suffix}]
    )
    assert app.notification_count_refresh_calls == 1


def test_toggle_agent_unread_refreshes_when_patch_fails() -> None:
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent], patch_result=False)

    app._toggle_agent_unread()

    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_toggle_agent_unread_ignores_focused_banner() -> None:
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._current_group_key = ("demo",)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_navigation_away_from_manual_unread_arms_it_without_clearing() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    app._manual_unread_agent_ids.add(first.identity)

    app._navigate_agents_panel(1)

    assert app.current_idx == 1
    assert first.identity in app._unread_completed_agent_ids
    assert first.identity not in app._manual_unread_agent_ids
    assert app.patch_calls == []


def test_navigation_back_to_armed_manual_unread_acknowledges_it() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second], current_idx=1)
    app._unread_completed_agent_ids.add(first.identity)

    app._navigate_agents_panel(-1)

    assert app.current_idx == 0
    assert first.identity not in app._unread_completed_agent_ids
    assert app.patch_calls == [first]


def test_keyboard_navigation_onto_clan_never_acknowledges_member() -> None:
    origin = make_agent(name="origin", status="RUNNING", raw_suffix="origin")
    member = make_agent(name="research.done", status="DONE", raw_suffix="done")
    member.agent_clan = "research"
    member.agent_clan_generation = "generation"
    container = project_clan_tree([member])[0]
    app = UnreadJumpApp([origin, container])
    app._unread_completed_agent_ids.add(member.identity)
    app._manual_unread_agent_ids.add(member.identity)

    app._navigate_agents_panel(1)

    assert app._agents[app.current_idx] is container
    assert app._unread_completed_agent_ids == {member.identity}
    assert app._manual_unread_agent_ids == {member.identity}
    assert app.patch_calls == []


def test_family_member_completion_notifications_project_to_one_node(
    notification_dismiss: Mock,
) -> None:
    notification_dismiss.return_value = 2
    family = make_agent(name="build", status="DONE", raw_suffix="family")
    family.agent_name = "build"
    family.agent_family = "build"
    family.agent_family_role = "root"
    plan = make_agent(name="build--plan", status="DONE", raw_suffix="plan")
    plan.agent_name = "build--plan"
    plan.agent_family = "build"
    plan.agent_family_role = "plan"
    plan.parent_timestamp = family.raw_suffix
    code = make_agent(name="build--code", status="DONE", raw_suffix="code")
    code.agent_name = "build--code"
    code.agent_family = "build"
    code.agent_family_role = "code"
    code.parent_timestamp = family.raw_suffix
    family.runtime_children = [plan, code]
    family.followup_agents = [plan, code]
    app = UnreadJumpApp([family, plan, code], current_idx=1)

    app._reconcile_unread_from_completion_notifications(
        [
            _completion_notification(plan, notification_id="plan"),
            _completion_notification(code, notification_id="code"),
        ]
    )

    assert app._unread_completed_agent_ids == {family.identity}
    assert plan.identity not in app._unread_completed_agent_ids
    assert code.identity not in app._unread_completed_agent_ids

    assert app._jump_to_next_unread_done_agent()

    assert app.current_idx == 0
    assert app._unread_completed_agent_ids == set()
    notification_dismiss.assert_called_once_with(
        [
            {"cl_name": family.cl_name, "raw_suffix": family.raw_suffix},
            {"cl_name": plan.cl_name, "raw_suffix": plan.raw_suffix},
            {"cl_name": code.cl_name, "raw_suffix": code.raw_suffix},
        ]
    )
    assert app.patch_calls == [family]


def test_plan_family_root_dismissal_includes_its_own_notification_key() -> None:
    """A plan-family root's own completion key must be dismissible.

    Regression: notification ownership borrowed the status-count projection,
    which substitutes a plan-family root for its concrete ``main`` workflow
    step. That step never owns a distinct completion notification, so the
    root's own key was dropped from the dismiss/mark-read key set.
    """
    raw_suffix = "root"
    root = make_agent(name="gh_sase-org__sase", status="DONE", raw_suffix=raw_suffix)
    root.agent_family = "gh_sase-org__sase"
    root.agent_family_role = "root"
    root.plan_chain_root = True
    root.role_suffix = "--plan"
    main_step = make_agent(name="main", status="DONE", raw_suffix=raw_suffix)
    main_step.parent_timestamp = root.raw_suffix
    main_step.parent_workflow = "ace-run"
    main_step.step_type = "agent"
    root.runtime_children = [main_step]
    root.followup_agents = [main_step]
    app = UnreadJumpApp([root, main_step])

    key_dicts = app._notification_key_dicts_for_agents([root])

    assert {"cl_name": root.cl_name, "raw_suffix": root.raw_suffix} in key_dicts


def test_manual_toggle_rejects_family_member_shell() -> None:
    family = make_agent(name="build", status="DONE", raw_suffix="family")
    family.agent_name = "build"
    family.agent_family = "build"
    family.agent_family_role = "root"
    child = make_agent(name="build--code", status="DONE", raw_suffix="code")
    child.agent_name = "build--code"
    child.agent_family = "build"
    child.agent_family_role = "code"
    child.parent_timestamp = family.raw_suffix
    family.followup_agents = [child]
    app = UnreadJumpApp([family, child], current_idx=1)

    app._toggle_agent_unread()

    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_has_unread_completed_agent_includes_plan_done() -> None:
    agent = make_agent(status="PLAN DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)

    assert app._has_unread_completed_agent()


def test_manual_unread_guards_per_row_dismissal(
    notification_dismiss: Mock,
) -> None:
    """A manually-unread row is never cleared or dismissed through the
    per-row helper. The user has to explicitly toggle the manual marker off
    before the row can be acknowledged and its notification dismissed.
    """
    agent = make_agent(status="DONE")
    app = UnreadJumpApp([agent])
    app._unread_completed_agent_ids.add(agent.identity)
    app._manual_unread_agent_ids.add(agent.identity)

    assert not app._clear_agent_unread_and_dismiss_notification(agent)
    assert agent.identity in app._unread_completed_agent_ids
    assert agent.identity in app._manual_unread_agent_ids
    notification_dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0

    assert not app._acknowledge_agent_unread(agent)
    assert agent.identity in app._unread_completed_agent_ids
    notification_dismiss.assert_not_called()


def test_bulk_unread_toggle_marks_restores_and_marks_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = Mock(return_value=2)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="FAILED", raw_suffix="second")
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([first, second, running])
    app._unread_completed_agent_ids.update(
        {first.identity, second.identity, running.identity}
    )
    app._manual_unread_agent_ids.add(second.identity)
    app._agent_info_metrics_cache = ("cached",)

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.MARKED_READ
    assert result.count == 2
    assert app._unread_completed_agent_ids == {running.identity}
    assert app._manual_unread_agent_ids == set()
    assert app._pending_bulk_read_agent_ids == {first.identity, second.identity}
    assert app._agent_info_metrics_cache is None
    dismiss.assert_called_once_with(
        [
            {"cl_name": first.cl_name, "raw_suffix": first.raw_suffix},
            {"cl_name": second.cl_name, "raw_suffix": second.raw_suffix},
        ]
    )
    assert app.notification_count_refresh_calls == 1
    assert app.refresh_calls == []
    assert app.patch_calls == [first, second]

    app.patch_calls.clear()
    app._agent_info_metrics_cache = ("cached",)

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.RESTORED_UNREAD
    assert result.count == 2
    assert app._unread_completed_agent_ids == {
        first.identity,
        second.identity,
        running.identity,
    }
    assert app._manual_unread_agent_ids == {first.identity, second.identity}
    assert app._pending_bulk_read_agent_ids is None
    assert app._agent_info_metrics_cache is None
    assert app.patch_calls == [first, second]
    dismiss.assert_called_once()

    app._reconcile_unread_from_completion_notifications([])
    assert first.identity in app._unread_completed_agent_ids
    assert second.identity in app._unread_completed_agent_ids
    assert running.identity not in app._unread_completed_agent_ids

    app.patch_calls.clear()

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.MARKED_READ
    assert result.count == 2
    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app._pending_bulk_read_agent_ids == {first.identity, second.identity}
    assert dismiss.call_count == 2


def test_bulk_unread_toggle_noops_without_terminal_unread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dismiss = Mock(return_value=0)
    monkeypatch.setattr(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        dismiss,
    )
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([running])
    app._unread_completed_agent_ids.add(running.identity)

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.NOOP
    assert result.count == 0
    assert app._unread_completed_agent_ids == {running.identity}
    assert app._pending_bulk_read_agent_ids is None
    dismiss.assert_not_called()
    assert app.notification_count_refresh_calls == 0
    assert app.refresh_calls == []
    assert app.patch_calls == []


def test_bulk_unread_restore_skips_missing_and_nonterminal_identities() -> None:
    restored = make_agent(name="restored", status="DONE", raw_suffix="restored")
    missing = make_agent(name="missing", status="DONE", raw_suffix="missing")
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([restored, running])
    app._pending_bulk_read_agent_ids = {
        restored.identity,
        missing.identity,
        running.identity,
    }

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.RESTORED_UNREAD
    assert result.count == 1
    assert app._unread_completed_agent_ids == {restored.identity}
    assert app._manual_unread_agent_ids == {restored.identity}
    assert app._pending_bulk_read_agent_ids is None
    assert app.patch_calls == [restored]


def test_bulk_unread_restore_noops_and_consumes_when_no_identity_is_eligible() -> None:
    running = make_agent(name="running", status="RUNNING", raw_suffix="running")
    app = UnreadJumpApp([running])
    app._pending_bulk_read_agent_ids = {running.identity}

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.NOOP
    assert app._pending_bulk_read_agent_ids is None
    assert app._unread_completed_agent_ids == set()
    assert app._manual_unread_agent_ids == set()
    assert app.patch_calls == []


def test_bulk_unread_mark_uses_refresh_fallback_and_invalidates_metrics() -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second], patch_result=False)
    app._unread_completed_agent_ids.update({first.identity, second.identity})
    app._agent_info_metrics_cache = ("cached",)

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.MARKED_READ
    assert app._agent_info_metrics_cache is None
    assert app.refresh_calls == [{"list_changed": True, "defer_detail": True}]


def test_manual_unread_add_invalidates_pending_bulk_read_undo(
    notification_dismiss: Mock,
) -> None:
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    app = UnreadJumpApp([first, second])
    app._unread_completed_agent_ids.add(first.identity)
    assert (
        app._toggle_all_unread_done_agents_read().outcome
        is BulkUnreadToggleOutcome.MARKED_READ
    )
    app.current_idx = 1

    app._toggle_agent_unread()

    assert app._pending_bulk_read_agent_ids is None
    assert app._unread_completed_agent_ids == {second.identity}
    assert app._manual_unread_agent_ids == {second.identity}

    app._toggle_agent_unread()
    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.NOOP
    assert first.identity not in app._unread_completed_agent_ids
    assert notification_dismiss.call_count == 2
