"""Tests for apply-state lazy Tier 2 reconcile transitions."""

from __future__ import annotations

import time

from sase.ace.tui.actions.agents._loading_apply import _agent_index_repair_notice
from sase.ace.tui.models.agent_loader import AgentLoadState
from tests._agents_tab_query_helpers import FakeAgentApp
from tests.ace.tui._lazy_tier2_reconcile_helpers import (
    apply_load,
    make_complete_load_state,
)


def test_apply_sets_pending_flag_without_scheduling_refresh() -> None:
    """A repair-state load marks reconcile pending without immediate reload."""
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0
    app._agents_refresh_pending = False
    app._agents_refresh_pending_full_history = False
    app._agents_refresh_scheduled = False
    app._agents_refresh_scheduled_full_history = False

    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="source_scan",
        used_artifact_index=False,
        repair_recommended=True,
        repair_reason="artifact_index_missing_bounded_fallback",
    )

    before = time.monotonic()
    apply_load(app, load_state)

    assert app._agents_history_reconcile_pending is True
    assert app._agents_history_reconcile_armed_mono >= before
    assert app._agents_refresh_pending is False
    assert app._agents_refresh_pending_full_history is False
    assert app._agents_refresh_scheduled is False


def test_apply_complete_visible_inbox_does_not_arm_history_reconcile() -> None:
    """Tier 1 can be archive-incomplete while complete for the visible inbox."""
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_history_reconcile_armed_mono = 0.0

    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    apply_load(app, load_state)

    assert app._agents_history_reconcile_pending is False
    assert app._agents_history_reconcile_armed_mono == 0.0


def test_apply_clears_pending_flag_on_complete_history() -> None:
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = True
    app._agents_history_reconcile_armed_mono = 42.0
    app._agents_seen_complete_history = False

    load_state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    apply_load(app, load_state)

    assert app._agents_history_reconcile_pending is False
    assert app._agents_seen_complete_history is True


def test_repair_notice_only_when_repair_recommended() -> None:
    """Repair diagnostics surface as an operator-visible notice."""
    healthy = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=True,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )
    repair = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="source_scan",
        used_artifact_index=False,
        repair_recommended=True,
        repair_reason="artifact_index_missing_bounded_fallback",
    )

    assert _agent_index_repair_notice(healthy) is None
    notice = _agent_index_repair_notice(repair)
    assert notice is not None
    assert "artifact_index_missing_bounded_fallback" in notice
    assert "sase agent index gc" in notice


def test_apply_repair_state_marks_reconcile_pending_without_timer() -> None:
    """Repair diagnostics defer full-history repair to idle/manual paths."""
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False

    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="source_scan",
            used_artifact_index=False,
            repair_recommended=True,
            repair_reason="artifact_index_missing_bounded_fallback",
        ),
    )

    assert app._agents_history_reconcile_pending is True
    assert app.timer_calls == []


def test_apply_incomplete_index_state_does_not_arm_reconcile() -> None:
    """An index-backed incomplete inbox is reported but not auto-promoted."""
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False

    apply_load(
        app,
        AgentLoadState(
            tier="tier1",
            complete_history=False,
            complete_visible_inbox=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
    )

    assert app._agents_history_reconcile_pending is False
    assert app.timer_calls == []


def test_apply_complete_history_does_not_arm_reconcile() -> None:
    """If a load returned complete history, no reconcile is armed."""
    app = FakeAgentApp()
    app._agents_history_reconcile_pending = False
    app._agents_seen_complete_history = False

    apply_load(app, make_complete_load_state())

    assert app.timer_calls == []
    assert app._agents_history_reconcile_pending is False
