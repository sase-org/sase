"""Tests for individual Agents-tab mark toggling."""

from __future__ import annotations

from unittest.mock import patch

from tests.ace.tui._agent_marking_helpers import _FakeMarkApp, _make_agent


def test_toggle_mark_adds_identity() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert a1.identity in app._marked_agents
    assert a2.identity not in app._marked_agents


def test_toggle_mark_auto_advances_cursor() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert app.current_idx == 1


def test_toggle_mark_auto_advance_acknowledges_unread_done_target() -> None:
    marked = _make_agent(cl_name="marked", raw_suffix="20240101120000")
    unread = _make_agent(
        cl_name="unread",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([marked, unread], patch_result=True)
    app._unread_completed_agent_ids.add(unread.identity)

    with patch(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        return_value=0,
    ) as dismiss_notifications:
        app._toggle_mark_agent()

    assert app.current_idx == 1
    assert marked.identity in app._marked_agents
    assert unread.identity not in app._unread_completed_agent_ids
    dismiss_notifications.assert_called_once_with(
        [{"cl_name": unread.cl_name, "raw_suffix": unread.raw_suffix}]
    )
    assert app.patch_calls.count(marked) == 1
    assert app.patch_calls.count(unread) == 1
    assert app.highlight_refresh_calls == 1
    assert app.refresh_calls == 0


def test_toggle_mark_acknowledges_unread_when_advance_wraps_to_same_row() -> None:
    unread = _make_agent(
        cl_name="unread",
        raw_suffix="20240101120000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([unread], patch_result=True)
    app._unread_completed_agent_ids.add(unread.identity)

    with patch(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        return_value=0,
    ) as dismiss_notifications:
        app._toggle_mark_agent()

    assert app.current_idx == 0
    assert unread.identity in app._marked_agents
    assert unread.identity not in app._unread_completed_agent_ids
    dismiss_notifications.assert_called_once_with(
        [{"cl_name": unread.cl_name, "raw_suffix": unread.raw_suffix}]
    )
    assert app.patch_calls == [unread]
    assert app.highlight_refresh_calls == 0
    assert app.refresh_calls == 0


def test_toggle_mark_manual_unread_target_stays_guarded_on_first_arrival() -> None:
    origin = _make_agent(cl_name="origin", raw_suffix="20240101120000")
    guarded = _make_agent(
        cl_name="guarded",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([origin, guarded], patch_result=True)
    app._unread_completed_agent_ids.add(guarded.identity)
    app._manual_unread_agent_ids.add(guarded.identity)

    with patch(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        return_value=0,
    ) as dismiss_notifications:
        app._toggle_mark_agent()

    assert app.current_idx == 1
    assert guarded.identity in app._unread_completed_agent_ids
    assert guarded.identity in app._manual_unread_agent_ids
    dismiss_notifications.assert_not_called()
    assert app.patch_calls.count(origin) == 1
    assert app.patch_calls.count(guarded) == 1
    assert app.highlight_refresh_calls == 1


def test_toggle_mark_arms_manual_unread_departure_before_return() -> None:
    guarded = _make_agent(
        cl_name="guarded",
        raw_suffix="20240101120000",
        status="DONE",
        pid=None,
    )
    other = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([guarded, other], patch_result=True)
    app._unread_completed_agent_ids.add(guarded.identity)
    app._manual_unread_agent_ids.add(guarded.identity)

    with patch(
        "sase.notifications.dismiss_agent_completion_notifications_matching_agents",
        return_value=0,
    ) as dismiss_notifications:
        app._toggle_mark_agent()

        assert app.current_idx == 1
        assert guarded.identity in app._unread_completed_agent_ids
        assert guarded.identity not in app._manual_unread_agent_ids
        dismiss_notifications.assert_not_called()

        app._toggle_mark_agent()

    assert app.current_idx == 0
    assert guarded.identity not in app._unread_completed_agent_ids
    dismiss_notifications.assert_called_once_with(
        [{"cl_name": guarded.cl_name, "raw_suffix": guarded.raw_suffix}]
    )


def test_toggle_mark_wraps_around() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])
    app.current_idx = 1

    app._toggle_mark_agent()

    assert app.current_idx == 0


def test_toggle_mark_advances_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 1  # alpha, visually first

    app._toggle_mark_agent()

    assert app.current_idx == 2
    assert app._agents[app.current_idx].cl_name == "b1"


def test_toggle_mark_wraps_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 0  # zeta, visually last

    app._toggle_mark_agent()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].cl_name == "a1"


def test_toggle_mark_advances_to_intervening_collapsed_banner_row() -> None:
    agents = [
        _make_agent(
            project_file="/tmp/projects/alpha/alpha.sase",
            cl_name="visible-a",
            raw_suffix="20240101100000",
        ),
        _make_agent(
            project_file="/tmp/projects/beta/beta.sase",
            cl_name="folded",
            raw_suffix="20240101110000",
        ),
        _make_agent(
            project_file="/tmp/projects/beta/beta.sase",
            cl_name="folded",
            raw_suffix="20240101110100",
        ),
        _make_agent(
            project_file="/tmp/projects/gamma/gamma.sase",
            cl_name="visible-g",
            raw_suffix="20240101120000",
        ),
    ]
    app = _FakeMarkApp(agents, patch_result=True)
    app._group_fold_registry.collapse(("beta", "folded"))
    app.current_idx = 0

    app._toggle_mark_agent()

    assert app._marked_agents == {agents[0].identity}
    assert app._current_group_key == ("beta", "folded")
    assert app.current_idx in {1, 2}
    assert app._agents[app.current_idx].cl_name == "folded"
    assert app.patch_calls == [agents[0]]
    assert app.highlight_refresh_calls == 1
    assert app.refresh_calls == 0


def test_toggle_mark_twice_removes_identity() -> None:
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    app._toggle_mark_agent()
    # With a single entry, cursor stays at 0 (no wraparound needed)
    assert app.current_idx == 0
    assert a1.identity in app._marked_agents
    app._toggle_mark_agent()

    assert a1.identity not in app._marked_agents


def test_toggle_mark_empty_panel_warns() -> None:
    app = _FakeMarkApp([])

    app._toggle_mark_agent()

    assert app._marked_agents == set()
    assert app.notifications == [("No agent selected", "warning")]
