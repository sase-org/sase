"""Leader dispatch: search, retired keys, unread/stopped jumps, and repeats.

Split from ``test_leader_keymap_dispatch``; see that module for the facade.
"""

from __future__ import annotations

from sase.ace.tui.models import _agent_stranded_cache as stranded_cache

from tests.ace.tui._leader_keymap_helpers import FakeApp


def test_leader_question_mark_is_retired_on_all_tabs() -> None:
    for tab in ("patches", "agents", "axe"):
        app = FakeApp(current_tab=tab)

        handled = app._handle_leader_key("question_mark")

        assert handled is True
        assert app._leader_mode_active is False
        assert app.show_help_count == 0
        assert app.notifications == []
        assert app._last_leader_key is None
        assert app.refresh_count == 1


def test_leader_slash_starts_metadata_search_only_on_agents() -> None:
    app = FakeApp(current_tab="agents")

    assert app._handle_leader_key("slash") is True
    assert app.search_forward_count == 1
    assert app.edit_query_count == 0
    assert app._last_leader_key == "slash"
    assert app.refresh_count == 1

    for tab in ("patches", "axe"):
        app = FakeApp(current_tab=tab)

        assert app._handle_leader_key("slash") is True
        assert app.search_forward_count == 0
        assert app.edit_query_count == 0
        assert app._last_leader_key is None
        assert app.refresh_count == 1


def test_leader_search_repeat_rechecks_agents_context() -> None:
    app = FakeApp(current_tab="agents")
    app._handle_leader_key("slash")
    app.current_tab = "patches"  # type: ignore[assignment]

    assert app._handle_leader_key("comma") is True
    assert app.search_forward_count == 1
    assert app.edit_query_count == 0
    assert app._last_leader_key == "slash"
    assert app.refresh_count == 2


def test_leader_g_is_retired_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("g")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.toggle_panel_grouping_count == 0
    assert app._last_leader_key is None
    assert app.refresh_count == 1


def test_stale_remembered_leader_g_cannot_toggle_panel_grouping() -> None:
    app = FakeApp(current_tab="patches")
    app._last_leader_key = "g"

    handled = app._handle_leader_key("comma")

    assert handled is True
    assert app.toggle_panel_grouping_count == 0
    assert app._last_leader_key == "g"
    assert app.refresh_count == 1


def test_leader_j_jumps_to_next_unread_done_agent_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.jump_unread_count == 1
    assert app.jump_stopped_count == 0
    assert app.notifications == []
    assert app.refresh_count == 0


def test_leader_j_records_and_repeat_invokes_unread_jump_again() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("j")
    repeated = app._handle_leader_key("comma")

    assert handled is True
    assert repeated is True
    assert app.jump_unread_count == 2
    assert app._last_leader_key == "j"
    assert app.refresh_count == 0


def test_leader_repeat_without_previous_command_notifies_and_refreshes() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("comma")

    assert handled is True
    assert app._last_leader_key is None
    assert app.notifications == ["No leader command to repeat"]
    assert app.refresh_count == 1


def test_leader_unknown_key_and_escape_do_not_overwrite_previous_command() -> None:
    app = FakeApp(current_tab="agents")
    app._handle_leader_key("j")

    app._handle_leader_key("unknown")
    app._handle_leader_key("escape")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "j"
    assert app.jump_unread_count == 2
    assert app.refresh_count == 2


def test_leader_repeat_does_not_record_repeat_subkey() -> None:
    app = FakeApp(current_tab="agents")

    app._handle_leader_key("j")
    app._handle_leader_key("comma")

    assert app._last_leader_key == "j"
    assert app.jump_unread_count == 2


def test_leader_j_notifies_when_no_unread_done_stopped_or_stranded_agent() -> None:
    app = FakeApp(current_tab="agents")
    app.jump_unread_result = False
    app.jump_stopped_result = False
    app.jump_stranded_result = False

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app.jump_unread_count == 1
    assert app.jump_stopped_count == 1
    assert app.jump_stranded_count == 1
    assert app.notifications == ["No unread completed, stopped, or stranded agents"]
    assert app.refresh_count == 0


def test_leader_j_triple_miss_names_stranded_backlog() -> None:
    from types import SimpleNamespace

    from sase.ace.tui.models import agent_stranded
    from sase.bead.stranded import StrandedReport
    from sase.core.stranded_work_facade import (
        StrandedWorkReport,
        StrandedWorkVerdict,
    )

    app = FakeApp(current_tab="agents")
    app.jump_unread_result = False
    app.jump_stopped_result = False
    app.jump_stranded_result = False
    app._agents = [SimpleNamespace(project_file="/tmp/demo/demo.sase")]
    try:
        stranded_cache._STRANDED_REPORT_CACHE.set(
            "demo",
            StrandedReport(
                report=StrandedWorkReport(
                    verdicts=(
                        StrandedWorkVerdict(
                            bead_id="sase-demo.1",
                            kind="phase",
                            state="stranded",
                            reason="unclosed",
                        ),
                        StrandedWorkVerdict(
                            bead_id="sase-demo.2",
                            kind="phase",
                            state="stranded",
                            reason="unclosed",
                        ),
                    ),
                    stranded_ids=("sase-demo.1", "sase-demo.2"),
                    blocked_ids=(),
                ),
                titles={},
                generated_at=1.0,
            ),
            "test",
        )

        handled = app._handle_leader_key("j")
    finally:
        stranded_cache._STRANDED_REPORT_CACHE.clear()

    assert handled is True
    assert app.jump_unread_count == 1
    assert app.jump_stopped_count == 1
    assert app.jump_stranded_count == 1
    assert app.notifications == [
        "No unread completed, stopped, or stranded agents · "
        "⚐ 2 stranded beads have no agent row here (Beads: status:stranded)"
    ]
    assert app.refresh_count == 0


def test_leader_j_falls_back_to_next_stopped_agent() -> None:
    app = FakeApp(current_tab="agents")
    app.jump_unread_result = False
    app.jump_stopped_result = True

    assert app._handle_leader_key("j") is True

    assert app.jump_unread_count == 1
    assert app.jump_stopped_count == 1
    assert app.jump_stranded_count == 0
    assert app.notifications == []
    assert app.refresh_count == 0


def test_leader_j_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    handled = app._handle_leader_key("j")

    assert handled is True
    assert app.jump_unread_count == 0
    assert app.jump_stopped_count == 0
    assert app.jump_stranded_count == 0
    assert app.notifications == []
    assert app.refresh_count == 0


def test_leader_shift_j_jumps_to_next_stopped_agent_on_agents_tab() -> None:
    app = FakeApp(current_tab="agents")

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.jump_stopped_count == 1
    assert app.jump_stranded_count == 0
    assert app.mark_all_unread_count == 0
    assert app.notifications == []
    assert app.refresh_count == 0


def test_leader_shift_j_notifies_when_no_stopped_agents() -> None:
    app = FakeApp(current_tab="agents")
    app.jump_stopped_result = False

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app.jump_stopped_count == 1
    assert app.notifications == ["No stopped agents"]
    assert app.refresh_count == 0


def test_leader_shift_j_noops_on_non_agents_tabs() -> None:
    app = FakeApp(current_tab="patches")

    handled = app._handle_leader_key("J")

    assert handled is True
    assert app.mark_all_unread_count == 0
    assert app.jump_stopped_count == 0
    assert app.jump_stranded_count == 0
    assert app.notifications == []
    assert app.refresh_count == 0


def test_leader_uppercase_l_jumps_to_last_error() -> None:
    app = FakeApp(current_tab="services")

    handled = app._handle_leader_key("L")

    assert handled is True
    assert app._leader_mode_active is False
    assert app.jump_to_last_error_count == 1
    assert app._last_leader_key == "L"
    assert app.refresh_count == 1
