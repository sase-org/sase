"""Bulk-ack scope and time-bound explicit undo (epic sase-1d7 phase sase-1d7.7).

`,u` covers every loaded unread terminal agent node across all Agents
tabs -- collapsed clans and tribes plus off-tab query rows -- through
the one predicate shared with the header unread count, and the undo is
an explicit toast-announced window rather than a silent toggle.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from sase.ace.tui.actions.agents._unread_bulk_scope import (
    BULK_READ_UNDO_WINDOW_SECONDS,
    bulk_unread_ack_targets,
)
from sase.ace.tui.actions.agents._unread_state import BulkUnreadToggleOutcome
from sase.ace.tui.models._agent_tree import project_clan_tree

from ._agent_unread_helpers import make_agent
from ._agent_unread_navigation_helpers import UnreadJumpApp
from ._leader_keymap_helpers import _FakeApp


@pytest.fixture(autouse=True)
def ack_completions(monkeypatch: pytest.MonkeyPatch) -> Mock:
    dismiss = Mock(
        return_value=SimpleNamespace(dismissed_ids={"n-acked"}, generation=7),
    )
    monkeypatch.setattr(
        "sase.notifications.ack_agent_completions",
        dismiss,
    )
    return dismiss


def _mixed_roster_app() -> UnreadJumpApp:
    """Build the epic-acceptance shape: collapsed clan, tribe, off-tab row."""
    first = make_agent(name="first", status="DONE", raw_suffix="first")
    first.agent_clan = "research"
    first.agent_clan_generation = "gen"
    second = make_agent(name="second", status="DONE", raw_suffix="second")
    second.agent_clan = "research"
    second.agent_clan_generation = "gen"
    container = project_clan_tree([first, second])[0]
    tribe_row = make_agent(name="tribe-row", status="DONE", raw_suffix="tribe")
    tribe_row.tribe = "jobs"
    off_tab = make_agent(name="off-tab", status="DONE", raw_suffix="off")
    app = UnreadJumpApp([container, tribe_row])
    app._agents_with_children = [container, first, second, tribe_row]
    app._agents_query_result = [container, first, second, tribe_row, off_tab]
    app._unread_completed_agent_ids.update(
        {first.identity, second.identity, tribe_row.identity, off_tab.identity}
    )
    app._agent_panel_index = lambda: SimpleNamespace(  # type: ignore[method-assign]
        non_child_indices=(0, 1),
        hidden_starting_indices=(),
    )
    return app


def test_bulk_ack_target_count_equals_header_count_across_scopes() -> None:
    app = _mixed_roster_app()
    header_before = app._agent_info_metrics()[0]

    targets = bulk_unread_ack_targets(app)
    assert {agent.identity for agent in targets} == set(app._unread_completed_agent_ids)
    assert len(targets) == 4

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.MARKED_READ
    assert result.count == 4
    assert result.count == header_before
    assert app._agent_info_metrics()[0] == 0


def test_bulk_ack_never_expands_a_panel() -> None:
    app = _mixed_roster_app()
    collapsed_before = set(app._collapsed_panel_keys)

    app._toggle_all_unread_done_agents_read()

    assert set(app._collapsed_panel_keys) == collapsed_before
    assert app.refresh_calls == []


def test_bulk_undo_inside_window_restores_same_identities() -> None:
    app = _mixed_roster_app()

    marked = app._toggle_all_unread_done_agents_read()
    assert marked.outcome is BulkUnreadToggleOutcome.MARKED_READ
    assert app._unread_completed_agent_ids == set()
    assert app._has_bulk_read_undo_available()

    restored = app._toggle_all_unread_done_agents_read()

    assert restored.outcome is BulkUnreadToggleOutcome.RESTORED_UNREAD
    assert restored.count == marked.count == 4
    assert app._unread_completed_agent_ids == {
        agent.identity for agent in bulk_unread_ack_targets(app)
    }
    assert len(app._unread_completed_agent_ids) == 4
    assert app._pending_bulk_read_agent_ids is None
    assert app._pending_bulk_read_armed_at is None
    assert not app._has_bulk_read_undo_available()


def test_bulk_undo_after_window_is_plain_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _mixed_roster_app()

    marked = app._toggle_all_unread_done_agents_read()
    assert marked.outcome is BulkUnreadToggleOutcome.MARKED_READ
    armed_at = app._pending_bulk_read_armed_at
    assert armed_at is not None
    assert app._has_bulk_read_undo_available()

    # The window closed (monkeypatched clock): the stale snapshot expires
    # instead of resurrecting rows.
    monkeypatch.setattr(
        time, "monotonic", lambda: armed_at + BULK_READ_UNDO_WINDOW_SECONDS + 1
    )
    assert not app._has_bulk_read_undo_available()

    result = app._toggle_all_unread_done_agents_read()

    assert result.outcome is BulkUnreadToggleOutcome.NOOP
    assert result.count == 0
    assert app._unread_completed_agent_ids == set()
    assert app._pending_bulk_read_agent_ids is None
    assert app._pending_bulk_read_armed_at is None


def test_leader_mark_toast_names_configured_chord_and_window() -> None:
    app = _FakeApp(current_tab="agents")

    assert app._handle_leader_key("u") is True

    assert app.notifications == [
        "Marked 2 completed agents read · press ,u within 10s to undo"
    ]


def test_leader_mark_toast_follows_remapped_chord() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry

    app = _FakeApp(current_tab="agents")
    app._keymap_registry = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {"keys": {"mark_all_unread_done_agents_read": "x"}}
                }
            }
        }
    )

    assert app._handle_leader_key("x") is True

    assert app.notifications == [
        "Marked 2 completed agents read · press ,x within 10s to undo"
    ]
