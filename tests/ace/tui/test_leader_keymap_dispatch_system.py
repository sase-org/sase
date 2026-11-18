"""Leader dispatch: refresh panel, bulk ack, updates, stash, and history.

Split from ``test_leader_keymap_dispatch``; see that module for the facade.
"""

from __future__ import annotations

import asyncio

from sase.ace.tui.actions.agents._unread_state import BulkUnreadToggleOutcome
from sase.ace.tui.actions.refresh_panel import FULL_HISTORY_MIGRATION_BANNER
from sase.ace.tui.keymaps import load_keymap_registry
from tests.ace.tui._leader_keymap_helpers import (
    BulkUnreadToggleResult,
    FakeApp,
)


def test_leader_y_opens_refresh_panel_on_full_history() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 0
    assert app.refresh_count == 1
    assert app.refresh_panel_opens == [
        {
            "initial_choice": "full_history",
            "banner": FULL_HISTORY_MIGRATION_BANNER,
        }
    ]


def test_leader_y_opens_refresh_panel_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    handled = app._handle_leader_key("y")

    assert handled is True
    assert app.full_history_refresh_count == 0
    assert app.refresh_count == 1
    assert app.refresh_panel_opens == [
        {
            "initial_choice": "full_history",
            "banner": FULL_HISTORY_MIGRATION_BANNER,
        }
    ]


def test_leader_u_marks_all_unread_done_agents_read_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.mark_all_unread_count == 1
    assert app.notifications == [
        "Marked 2 completed agents read · press ,u within 10s to undo"
    ]
    assert app.refresh_count == 0


def test_leader_u_notifies_when_no_unread_done_agents() -> None:
    app = FakeApp(current_tab="agents")
    app.mark_all_unread_result = BulkUnreadToggleResult(BulkUnreadToggleOutcome.NOOP)

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["No unread completed agents"]
    assert app.refresh_count == 1


def test_leader_u_notifies_when_bulk_read_is_restored() -> None:
    app = FakeApp(current_tab="agents")
    app.mark_all_unread_result = BulkUnreadToggleResult(
        BulkUnreadToggleOutcome.RESTORED_UNREAD,
        2,
    )

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 1
    assert app.notifications == ["Restored 2 completed agents unread"]
    assert app.refresh_count == 0


def test_leader_u_off_tab_finishes_perf_sample() -> None:
    """An off-tab ,u still closes the leader perf sample like ,j/,J."""
    from types import SimpleNamespace

    app = FakeApp(current_tab="patches")
    begins: list[str] = []
    paints: list[bool] = []
    app._jk_perf_begin = begins.append  # type: ignore[attr-defined]
    app._jk_perf = SimpleNamespace(mark_painted=lambda: paints.append(True))  # type: ignore[attr-defined]
    app.call_after_refresh = lambda callback: callback()  # type: ignore[attr-defined]

    handled = app._handle_leader_key("u")

    assert handled is True
    assert app.mark_all_unread_count == 0
    assert app.refresh_count == 1
    assert begins == [",u"]
    assert paints == [True]


def test_leader_u_records_and_repeat_invokes_bulk_toggle_again() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("u")
    app.mark_all_unread_result = BulkUnreadToggleResult(
        BulkUnreadToggleOutcome.RESTORED_UNREAD,
        2,
    )
    repeated = app._handle_leader_key("comma")

    assert handled is True
    assert repeated is True
    assert app.mark_all_unread_count == 2
    assert app._last_leader_key == "u"
    assert app.notifications == [
        "Marked 2 completed agents read · press ,u within 10s to undo",
        "Restored 2 completed agents unread",
    ]
    assert app.refresh_count == 0


def test_leader_uppercase_u_opens_sase_update_shortcut() -> None:
    app = FakeApp(current_tab="services")

    handled = app._handle_leader_key("U")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.update_sase_shortcut_count == 1
    assert app._last_leader_key == "U"
    assert app.refresh_count == 1


def test_leader_uppercase_e_runs_update_everything_on_all_tabs() -> None:
    for tab in ("patches", "agents", "axe"):
        app = FakeApp(current_tab=tab)

        handled = app._handle_leader_key("E")

        assert handled is True
        assert app._leader_mode_active is False
        assert app.update_everything_shortcut_count == 1
        assert app.update_sase_shortcut_count == 0
        assert app._last_leader_key == "E"
        assert app.refresh_count == 1


def test_leader_update_everything_repeat_and_remap_use_configured_key() -> None:
    app = FakeApp(current_tab="services")
    app._keymap_registry = load_keymap_registry(
        {"keymaps": {"modes": {"leader_mode": {"keys": {"update_everything": "Q"}}}}}
    )

    assert app._handle_leader_key("E") is True
    assert app.update_everything_shortcut_count == 0
    assert app._last_leader_key is None
    assert app.refresh_count == 1

    assert app._handle_leader_key("Q") is True
    assert app._handle_leader_key("comma") is True
    assert app.update_everything_shortcut_count == 2
    assert app._last_leader_key == "Q"
    assert app.refresh_count == 3


def test_leader_at_schedules_panel_only_action_and_repeat() -> None:
    app = FakeApp(current_tab="services")

    handled = app._handle_leader_key("at")

    assert handled is True
    assert app._leader_mode_active is False
    assert app._last_leader_key == "at"
    assert app.scheduled_callbacks == [app.action_open_prompt_stash]
    assert app.refresh_count == 1

    asyncio.run(app.scheduled_callbacks.pop()())
    assert app.open_prompt_stash_count == 1

    repeated = app._handle_leader_key("comma")
    assert repeated is True
    assert app._last_leader_key == "at"
    assert app.scheduled_callbacks == [app.action_open_prompt_stash]
    assert app.refresh_count == 2


def test_leader_ctrl_g_edits_first_prompt_history_entry() -> None:
    app = FakeApp()

    handled = app._handle_leader_key("ctrl+g")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.prompt_history_calls == [{"show_cancelled": False, "edit_first": True}]
    assert app.refresh_count == 1
